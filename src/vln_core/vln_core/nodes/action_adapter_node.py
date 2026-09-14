"""ROS 2 Node for vln_action_adapter."""

import sys
from typing import Optional

try:
    import rclpy
    from rclpy.node import Node
    from geometry_msgs.msg import TwistStamped
    from vln_interfaces.msg import PolicyAction
except ImportError:
    # Allow importing and linting in non-ROS development environments (e.g. macOS)
    rclpy = None
    Node = object
    TwistStamped = None
    PolicyAction = None

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
            TwistStamped,
            '/vln/raw_cmd_vel',
            qos_profile,
        )

        self.get_logger().info(
            f"vln_action_adapter started (stop_threshold={stop_threshold}, "
            f"consecutive_frames={consecutive_frames})"
        )

    def action_callback(self, msg: PolicyAction):
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
        )

        twist_data, stop_triggered, detail = self.adapter.process_action(action_data)

        if stop_triggered:
            self.get_logger().info(f"[STOP_LATCH] {detail}")

        # Publish TwistStamped
        out_msg = TwistStamped()
        out_msg.header.stamp = msg.header.stamp
        out_msg.header.frame_id = "base_link"
        out_msg.twist.linear.x = float(twist_data.linear_x)
        out_msg.twist.angular.z = float(twist_data.angular_z)

        self.raw_cmd_pub.publish(out_msg)


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
