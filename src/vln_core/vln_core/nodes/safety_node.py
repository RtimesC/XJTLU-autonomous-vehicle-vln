"""ROS 2 Node for vln_safety_node."""

import sys
from typing import Optional

try:
    import rclpy
    from rclpy.node import Node
    from geometry_msgs.msg import TwistStamped
    from vln_interfaces.msg import SafetyStatus
except ImportError:
    rclpy = None
    Node = object
    TwistStamped = None
    SafetyStatus = None

from vln_core.protocol import TwistStampedData
from vln_core.safety_filter import SafetyFilter, SafetyFilterConfig


class VlnSafetyNode(Node if rclpy else object):
    """ROS 2 Node enforcing kinematic constraints, watchdogs, and active zeroing."""

    def __init__(self):
        if rclpy is None:
            raise RuntimeError("rclpy is not installed; cannot initialize VlnSafetyNode")
        super().__init__('vln_safety_node')

        # Declare parameters
        self.declare_parameter('max_linear_velocity', 0.8)
        self.declare_parameter('min_linear_velocity', -0.2)
        self.declare_parameter('max_angular_velocity', 1.0)
        self.declare_parameter('max_linear_accel', 0.8)
        self.declare_parameter('max_angular_accel', 1.5)
        self.declare_parameter('watchdog_timeout_sec', 0.4)
        self.declare_parameter('timer_frequency_hz', 20.0)

        max_v = self.get_parameter('max_linear_velocity').get_parameter_value().double_value
        min_v = self.get_parameter('min_linear_velocity').get_parameter_value().double_value
        max_w = self.get_parameter('max_angular_velocity').get_parameter_value().double_value
        max_a = self.get_parameter('max_linear_accel').get_parameter_value().double_value
        max_alpha = self.get_parameter('max_angular_accel').get_parameter_value().double_value
        watchdog_sec = self.get_parameter('watchdog_timeout_sec').get_parameter_value().double_value
        timer_hz = self.get_parameter('timer_frequency_hz').get_parameter_value().double_value

        config = SafetyFilterConfig(
            max_linear_velocity=max_v,
            min_linear_velocity=min_v,
            max_angular_velocity=max_w,
            max_linear_accel=max_a,
            max_angular_accel=max_alpha,
            watchdog_timeout_sec=watchdog_sec,
        )
        self.filter = SafetyFilter(config=config)

        # QoS
        qos_cmd = rclpy.qos.QoSProfile(
            reliability=rclpy.qos.ReliabilityPolicy.RELIABLE,
            history=rclpy.qos.HistoryPolicy.KEEP_LAST,
            depth=1,
        )
        qos_status = rclpy.qos.QoSProfile(
            reliability=rclpy.qos.ReliabilityPolicy.RELIABLE,
            history=rclpy.qos.HistoryPolicy.KEEP_LAST,
            depth=20,
        )

        self.raw_cmd_sub = self.create_subscription(
            TwistStamped,
            '/vln/raw_cmd_vel',
            self.raw_cmd_callback,
            qos_cmd,
        )

        self.safe_cmd_pub = self.create_publisher(
            TwistStamped,
            '/vln/safe_cmd_vel',
            qos_cmd,
        )

        self.safety_status_pub = self.create_publisher(
            SafetyStatus,
            '/vln/safety_status',
            qos_status,
        )

        # Active Watchdog Timer (checks freshness and actively emits zero velocity if timed out)
        timer_period = 1.0 / max(1.0, timer_hz)
        self.watchdog_timer = self.create_wall_timer(timer_period, self.watchdog_timer_callback)

        self.current_episode_id = "default_episode"
        self.current_seq_id = 0

        self.get_logger().info(
            f"vln_safety_node started (max_v={max_v}, max_w={max_w}, "
            f"watchdog={watchdog_sec * 1000.0:.0f}ms)"
        )

    def raw_cmd_callback(self, msg: TwistStamped):
        stamp_sec = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9
        raw_data = TwistStampedData(
            header_stamp_sec=stamp_sec,
            linear_x=msg.twist.linear.x,
            angular_z=msg.twist.angular.z,
            frame_id="base_link",
        )

        self.current_seq_id += 1
        safe_data, status_data = self.filter.filter_command(
            raw_cmd=raw_data,
            episode_id=self.current_episode_id,
            action_sequence_id=self.current_seq_id,
        )

        self._publish_outputs(safe_data, status_data)

    def watchdog_timer_callback(self):
        safe_data, status_data = self.filter.check_watchdog(
            episode_id=self.current_episode_id,
            action_seq_id=self.current_seq_id,
        )

        # If watchdog is tripped (timeout), actively publish zero-velocity command
        if status_data.policy_timeout:
            self._publish_outputs(safe_data, status_data)

    def _publish_outputs(self, safe_data: TwistStampedData, status_data):
        now_time = self.get_clock().now().to_msg()

        # 1. Publish safe TwistStamped
        safe_msg = TwistStamped()
        safe_msg.header.stamp = now_time
        safe_msg.header.frame_id = "base_link"
        safe_msg.twist.linear.x = float(safe_data.linear_x)
        safe_msg.twist.angular.z = float(safe_data.angular_z)
        self.safe_cmd_pub.publish(safe_msg)

        # 2. Publish SafetyStatus
        status_msg = SafetyStatus()
        status_msg.header.stamp = now_time
        status_msg.header.frame_id = "base_link"
        status_msg.episode_id = status_data.episode_id
        status_msg.action_sequence_id = status_data.action_sequence_id
        status_msg.command_accepted = status_data.command_accepted
        status_msg.command_modified = status_data.command_modified
        status_msg.emergency_stop = status_data.emergency_stop
        status_msg.policy_timeout = status_data.policy_timeout
        status_msg.human_takeover = status_data.human_takeover
        status_msg.reason_code = int(status_data.reason_code)
        status_msg.reason_detail = str(status_data.reason_detail)
        self.safety_status_pub.publish(status_msg)


def main(args=None):
    if rclpy is None:
        print("Error: rclpy not available on this system.", file=sys.stderr)
        return 1
    rclpy.init(args=args)
    node = VlnSafetyNode()
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
