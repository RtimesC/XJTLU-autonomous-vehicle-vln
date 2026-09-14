"""ROS 2 Node providing NavigateLanguage Action Server and lifecycle governance."""

import sys
import time
from typing import Optional

try:
    import rclpy
    from rclpy.action import ActionServer, CancelResponse, GoalResponse
    from rclpy.node import Node
    from vln_interfaces.action import NavigateLanguage
    from vln_interfaces.msg import EpisodeControl, EpisodeEvent, PolicyAction
except ImportError:
    rclpy = None
    Node = object
    ActionServer = None
    CancelResponse = None
    GoalResponse = None
    NavigateLanguage = None
    EpisodeControl = None
    EpisodeEvent = None
    PolicyAction = None

from vln_core.episode_manager import EpisodeManager, EpisodeManagerConfig, EpisodeState


class VlnEpisodeManagerNode(Node if rclpy else object):
    """ROS 2 Action Server managing NavigateLanguage goals and episode results."""

    def __init__(self):
        if rclpy is None:
            raise RuntimeError("rclpy is not installed; cannot initialize VlnEpisodeManagerNode")
        super().__init__('vln_episode_manager_node')

        self.declare_parameter('max_duration_sec', 60.0)
        self.declare_parameter('max_steps', 500)

        max_dur = self.get_parameter('max_duration_sec').get_parameter_value().double_value
        max_steps = self.get_parameter('max_steps').get_parameter_value().integer_value

        config = EpisodeManagerConfig(max_duration_sec=max_dur, max_steps=max_steps)
        self.manager = EpisodeManager(config=config)

        self._active_goal_handle = None

        # Action Server
        self._action_server = ActionServer(
            self,
            NavigateLanguage,
            '/vln/navigate_language',
            execute_callback=self.execute_callback,
            goal_callback=self.goal_callback,
            cancel_callback=self.cancel_callback,
        )

        # The manager is the sole owner of episode identity. Consumers receive
        # a durable control message rather than a bare instruction string.
        qos_control = rclpy.qos.QoSProfile(
            reliability=rclpy.qos.ReliabilityPolicy.RELIABLE,
            durability=rclpy.qos.DurabilityPolicy.TRANSIENT_LOCAL,
            history=rclpy.qos.HistoryPolicy.KEEP_LAST,
            depth=1,
        )
        self.instruction_pub = self.create_publisher(
            EpisodeControl,
            '/vln/episode_control',
            qos_control,
        )

        # Subscriber to monitor adapter-confirmed terminal events.
        qos_profile = rclpy.qos.QoSProfile(
            reliability=rclpy.qos.ReliabilityPolicy.RELIABLE,
            history=rclpy.qos.HistoryPolicy.KEEP_LAST,
            depth=1,
        )
        self.action_sub = self.create_subscription(
            EpisodeEvent,
            '/vln/episode_event',
            self.event_callback,
            qos_profile,
        )
        self.policy_action_sub = self.create_subscription(
            PolicyAction,
            '/vln/policy_action',
            self.policy_action_callback,
            qos_profile,
        )
        self.timeout_timer = self.create_timer(0.05, self.timeout_callback)

        self.get_logger().info(
            f"vln_episode_manager_node initialized (max_dur={max_dur}s, max_steps={max_steps})"
        )

    def goal_callback(self, goal_request):
        ep_id = goal_request.episode_id
        instruction = goal_request.instruction
        success, reason = self.manager.start_episode(ep_id, instruction)
        if not success:
            self.get_logger().warn(f"Rejecting goal: {reason}")
            return GoalResponse.REJECT

        self.get_logger().info(f"Accepted goal '{ep_id}': '{instruction}'")
        # Publish the complete context, including the client-provided ID.
        msg = EpisodeControl()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.episode_id = ep_id
        msg.instruction = instruction
        msg.command = EpisodeControl.COMMAND_START
        self.instruction_pub.publish(msg)
        return GoalResponse.ACCEPT

    def cancel_callback(self, goal_handle):
        self.get_logger().info("Received cancellation request for active episode.")
        ok, _ = self.manager.cancel_episode(reason="client_requested_cancel")
        if ok:
            self._publish_control(
                EpisodeControl.COMMAND_CANCEL,
                self.manager.active_record.episode_id,
                "client_requested_cancel",
            )
        return CancelResponse.ACCEPT

    def execute_callback(self, goal_handle):
        self._active_goal_handle = goal_handle
        self.get_logger().info(f"Executing episode '{goal_handle.request.episode_id}'...")

        # Feedback & monitoring loop
        while self.manager.is_running:
            rec = self.manager.active_record
            if rec is not None:
                feedback_msg = NavigateLanguage.Feedback()
                feedback_msg.state = rec.state.value
                feedback_msg.latest_action_sequence_id = rec.latest_sequence_id
                feedback_msg.latest_stop_probability = rec.latest_stop_probability
                goal_handle.publish_feedback(feedback_msg)

            time.sleep(0.05)

        # Finished or cancelled
        rec = self.manager.active_record
        result = NavigateLanguage.Result()
        if rec is not None:
            result.completed = rec.completed
            result.termination_reason = rec.termination_reason
            result.elapsed_time_s = float(rec.elapsed_time_s)

        if goal_handle.is_cancel_requested or (rec and rec.state == EpisodeState.CANCELLED):
            goal_handle.canceled()
            self.get_logger().info(f"Episode '{rec.episode_id}' cancelled: {rec.termination_reason}")
        elif rec and rec.completed:
            goal_handle.succeed()
            self.get_logger().info(f"Episode '{rec.episode_id}' succeeded: {rec.termination_reason}")
        else:
            goal_handle.abort()
            self.get_logger().warn(f"Episode '{rec.episode_id}' aborted: {rec.termination_reason}")

        self._active_goal_handle = None
        return result

    def _publish_control(self, command: int, episode_id: str, reason: str):
        msg = EpisodeControl()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.episode_id = episode_id
        msg.command = command
        msg.reason = reason
        self.instruction_pub.publish(msg)

    def event_callback(self, msg: EpisodeEvent):
        if not self.manager.is_running or msg.episode_id != self.manager.active_record.episode_id:
            return
        if msg.event_type == EpisodeEvent.EVENT_STOP_LATCH:
            self.manager.update_action(
                sequence_id=msg.action_sequence_id,
                stop_probability=1.0,
                is_latched_stopped=True,
            )
        elif msg.event_type == EpisodeEvent.EVENT_POLICY_FAILED:
            self.manager.fail_episode(reason=msg.reason or "policy_failed")
        if not self.manager.is_running:
            rec = self.manager.active_record
            self._publish_control(
                EpisodeControl.COMMAND_TERMINATE,
                rec.episode_id,
                rec.termination_reason,
            )

    def policy_action_callback(self, msg: PolicyAction):
        """Tracks progress and max-steps without allowing raw p_stop to finish."""
        if not self.manager.is_running or msg.episode_id != self.manager.active_record.episode_id:
            return
        finished, _ = self.manager.update_action(
            sequence_id=msg.sequence_id,
            stop_probability=msg.stop_probability,
            is_latched_stopped=False,
        )
        if finished:
            rec = self.manager.active_record
            self._publish_control(
                EpisodeControl.COMMAND_TERMINATE,
                rec.episode_id,
                rec.termination_reason,
            )

    def timeout_callback(self):
        if not self.manager.is_running:
            return
        finished, _ = self.manager.check_timeout()
        if finished:
            rec = self.manager.active_record
            self._publish_control(
                EpisodeControl.COMMAND_TERMINATE,
                rec.episode_id,
                rec.termination_reason,
            )


def main(args=None):
    if rclpy is None:
        print("Error: rclpy not available on this system.", file=sys.stderr)
        return 1
    rclpy.init(args=args)
    node = VlnEpisodeManagerNode()
    from rclpy.executors import MultiThreadedExecutor
    executor = MultiThreadedExecutor(num_threads=3)
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        executor.remove_node(node)
        node.destroy_node()
        rclpy.shutdown()
    return 0


if __name__ == '__main__':
    sys.exit(main())
