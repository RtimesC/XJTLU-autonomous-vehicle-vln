"""ROS 2 Node providing NavigateLanguage Action Server and lifecycle governance."""

import sys
import time
from typing import Optional

try:
    import rclpy
    from rclpy.action import ActionServer, CancelResponse, GoalResponse
    from rclpy.node import Node
    from std_msgs.msg import String
    from vln_interfaces.action import NavigateLanguage
    from vln_interfaces.msg import PolicyAction
except ImportError:
    rclpy = None
    Node = object
    ActionServer = None
    CancelResponse = None
    GoalResponse = None
    String = None
    NavigateLanguage = None
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

        # Publisher to notify policy nodes of the new goal instruction
        self.instruction_pub = self.create_publisher(
            String,
            '/vln/goal_instruction',
            10,
        )

        # Subscriber to monitor policy actions
        qos_profile = rclpy.qos.QoSProfile(
            reliability=rclpy.qos.ReliabilityPolicy.RELIABLE,
            history=rclpy.qos.HistoryPolicy.KEEP_LAST,
            depth=1,
        )
        self.action_sub = self.create_subscription(
            PolicyAction,
            '/vln/policy_action',
            self.action_callback,
            qos_profile,
        )

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
        # Publish instruction to policy
        msg = String()
        msg.data = instruction
        self.instruction_pub.publish(msg)
        return GoalResponse.ACCEPT

    def cancel_callback(self, goal_handle):
        self.get_logger().info("Received cancellation request for active episode.")
        self.manager.cancel_episode(reason="client_requested_cancel")
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

    def action_callback(self, msg: PolicyAction):
        if not self.manager.is_running:
            return

        is_stopped = (msg.stop_probability >= 0.80 and msg.linear_velocity == 0.0)
        self.manager.update_action(
            sequence_id=msg.sequence_id,
            stop_probability=msg.stop_probability,
            is_latched_stopped=is_stopped,
        )


def main(args=None):
    if rclpy is None:
        print("Error: rclpy not available on this system.", file=sys.stderr)
        return 1
    rclpy.init(args=args)
    node = VlnEpisodeManagerNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()
    return 0


if __name__ == '__main__':
    sys.exit(main())
