"""ROS 2 Node for vln_action_adapter."""

import sys
from typing import Optional

try:
    import rclpy
    from rclpy.node import Node
    from vln_interfaces.msg import EpisodeControl, EpisodeEvent, PolicyAction, VlnCommand
except ImportError:
    # Allow importing and linting in non-ROS development environments (e.g. macOS)
    rclpy = None
    Node = object
    EpisodeControl = None
    EpisodeEvent = None
    PolicyAction = None
    VlnCommand = None

from vln_core.action_adapter import ActionAdapter, ActionAdapterConfig
from vln_core.protocol import PolicyActionData


class VlnActionAdapterNode(Node if rclpy else object):
    """ROS 2 Node translating /vln/policy_action into /vln/raw_cmd_vel."""

    def __init__(self):
        if rclpy is None:
            raise RuntimeError("rclpy is not installed; cannot initialize VlnActionAdapterNode")
        super().__init__('vln_action_adapter')

        # Declare parameters
        self.declare_parameter('stop_threshold', 0.8)
        self.declare_parameter('consecutive_stop_frames', 3)

        stop_threshold = self.get_parameter('stop_threshold').get_parameter_value().double_value
        consecutive_frames = self.get_parameter('consecutive_stop_frames').get_parameter_value().integer_value

        config = ActionAdapterConfig(
            stop_threshold=stop_threshold,
            consecutive_stop_frames=consecutive_frames,
        )
        self.adapter = ActionAdapter(config=config)
        self._active_episode_id: Optional[str] = None

        # QoS: Reliable, Keep Last 1
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

        self.raw_cmd_pub = self.create_publisher(
            VlnCommand,
            '/vln/raw_cmd_vel',
            qos_profile,
        )
        self.event_pub = self.create_publisher(EpisodeEvent, '/vln/episode_event', qos_profile)

        qos_control = rclpy.qos.QoSProfile(
            reliability=rclpy.qos.ReliabilityPolicy.RELIABLE,
            durability=rclpy.qos.DurabilityPolicy.TRANSIENT_LOCAL,
            history=rclpy.qos.HistoryPolicy.KEEP_LAST,
            depth=1,
        )
        self.control_sub = self.create_subscription(
            EpisodeControl,
            '/vln/episode_control',
            self.control_callback,
            qos_control,
        )

        self.get_logger().info(
            f"vln_action_adapter started (stop_threshold={stop_threshold}, "
            f"consecutive_frames={consecutive_frames})"
        )

    def control_callback(self, msg: EpisodeControl):
        if msg.command == EpisodeControl.COMMAND_START:
            self.adapter.reset_episode(msg.episode_id)
            self._active_episode_id = msg.episode_id
            self.get_logger().info(f"Adapter started episode '{msg.episode_id}'.")
        elif self._active_episode_id == msg.episode_id:
            self._active_episode_id = None
            self.adapter.reset_episode("")
            self.get_logger().info(f"Adapter stopped episode '{msg.episode_id}': {msg.reason}")

    def action_callback(self, msg: PolicyAction):
        if not self._active_episode_id:
            return
        # Extract time from header
        stamp_sec = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9

        action_data = PolicyActionData(
            header_stamp_sec=stamp_sec,
            frame_id=msg.header.frame_id or "base_link",
            episode_id=msg.episode_id,
            sequence_id=msg.sequence_id,
            linear_velocity=msg.linear_velocity,
            angular_velocity=msg.angular_velocity,
            stop_probability=msg.stop_probability,
            inference_latency_ms=msg.inference_latency_ms,
            valid=msg.valid,
            model_version=msg.model_version,
            outcome=msg.outcome,
            outcome_detail=msg.outcome_detail,
        )

        twist_data, stop_triggered, detail = self.adapter.process_action(
            action_data, expected_episode_id=self._active_episode_id
        )

        if stop_triggered:
            self.get_logger().info(f"[STOP_LATCH] {detail}")

        # Publish a command envelope so safety and logs retain episode and
        # policy sequence identity after the PolicyAction is transformed.
        out_msg = VlnCommand()
        out_msg.header.stamp = msg.header.stamp
        out_msg.header.frame_id = "base_link"
        out_msg.episode_id = self._active_episode_id
        out_msg.policy_sequence_id = msg.sequence_id
        out_msg.twist.linear.x = float(twist_data.linear_x)
        out_msg.twist.angular.z = float(twist_data.angular_z)

        self.raw_cmd_pub.publish(out_msg)

        if stop_triggered or msg.outcome == PolicyAction.OUTCOME_FAILED:
            event = EpisodeEvent()
            event.header.stamp = msg.header.stamp
            event.header.frame_id = "base_link"
            event.episode_id = self._active_episode_id
            event.action_sequence_id = msg.sequence_id
            event.event_type = (
                EpisodeEvent.EVENT_STOP_LATCH if stop_triggered else EpisodeEvent.EVENT_POLICY_FAILED
            )
            event.reason = detail or msg.outcome_detail
            self.event_pub.publish(event)


def main(args=None):
    if rclpy is None:
        print("Error: rclpy not available on this system.", file=sys.stderr)
        return 1
    rclpy.init(args=args)
    node = VlnActionAdapterNode()
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
