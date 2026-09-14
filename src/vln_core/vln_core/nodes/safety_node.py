"""ROS 2 Node for vln_safety_node."""

import sys
try:
    import rclpy
    from rclpy.node import Node
    from std_msgs.msg import Bool
    from vln_interfaces.msg import EpisodeControl, SafetyStatus, VlnCommand
except ImportError:
    rclpy = None
    Node = object
    Bool = None
    EpisodeControl = None
    SafetyStatus = None
    VlnCommand = None

from vln_core.protocol import ReasonCode, SafetyStatusData, TwistStampedData
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
        self.declare_parameter('max_action_age_sec', 0.5)
        self.declare_parameter('timer_frequency_hz', 20.0)

        max_v = self.get_parameter('max_linear_velocity').get_parameter_value().double_value
        min_v = self.get_parameter('min_linear_velocity').get_parameter_value().double_value
        max_w = self.get_parameter('max_angular_velocity').get_parameter_value().double_value
        max_a = self.get_parameter('max_linear_accel').get_parameter_value().double_value
        max_alpha = self.get_parameter('max_angular_accel').get_parameter_value().double_value
        watchdog_sec = self.get_parameter('watchdog_timeout_sec').get_parameter_value().double_value
        max_age_sec = self.get_parameter('max_action_age_sec').get_parameter_value().double_value
        timer_hz = self.get_parameter('timer_frequency_hz').get_parameter_value().double_value

        config = SafetyFilterConfig(
            max_linear_velocity=max_v,
            min_linear_velocity=min_v,
            max_angular_velocity=max_w,
            max_linear_accel=max_a,
            max_angular_accel=max_alpha,
            watchdog_timeout_sec=watchdog_sec,
            max_action_age_sec=max_age_sec,
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
            VlnCommand,
            '/vln/raw_cmd_vel',
            self.raw_cmd_callback,
            qos_cmd,
        )

        self.safe_cmd_pub = self.create_publisher(
            VlnCommand,
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

        self.current_episode_id = ""
        self.current_seq_id = 0
        self._control_active = False

        qos_control = rclpy.qos.QoSProfile(
            reliability=rclpy.qos.ReliabilityPolicy.RELIABLE,
            durability=rclpy.qos.DurabilityPolicy.TRANSIENT_LOCAL,
            history=rclpy.qos.HistoryPolicy.KEEP_LAST,
            depth=1,
        )
        self.control_sub = self.create_subscription(
            EpisodeControl, '/vln/episode_control', self.control_callback, qos_control
        )
        self.estop_sub = self.create_subscription(
            Bool, '/vln/control/emergency_stop', self.emergency_stop_callback, 10
        )
        self.takeover_sub = self.create_subscription(
            Bool, '/vln/control/human_takeover', self.human_takeover_callback, 10
        )
        self.arbiter_sub = self.create_subscription(
            Bool, '/vln/control/arbiter_granted', self.arbiter_granted_callback, 10
        )

        self.get_logger().info(
            f"vln_safety_node started (max_v={max_v}, max_w={max_w}, "
            f"watchdog={watchdog_sec * 1000.0:.0f}ms)"
        )

    def control_callback(self, msg: EpisodeControl):
        if msg.command == EpisodeControl.COMMAND_START:
            self.filter.reset(preserve_overrides=True)
            self.current_episode_id = msg.episode_id
            self.current_seq_id = 0
            self._control_active = True
            return

        if msg.episode_id == self.current_episode_id:
            self._control_active = False
            self.filter.reset()
            self._publish_zero(msg.episode_id, 0, msg.reason or "episode terminated")

    def emergency_stop_callback(self, msg: Bool):
        self.filter.set_emergency_stop(bool(msg.data))
        if msg.data:
            self._publish_zero(
                self.current_episode_id, self.current_seq_id, "emergency stop active",
                ReasonCode.REASON_EMERGENCY_STOP,
            )

    def human_takeover_callback(self, msg: Bool):
        self.filter.set_human_takeover(bool(msg.data))
        if msg.data:
            self._publish_zero(
                self.current_episode_id, self.current_seq_id, "human takeover active",
                ReasonCode.REASON_HUMAN_TAKEOVER,
            )

    def arbiter_granted_callback(self, msg: Bool):
        self.filter.set_arbiter_denied(not bool(msg.data))
        if not msg.data:
            self._publish_zero(
                self.current_episode_id, self.current_seq_id, "arbiter denied VLN control",
                ReasonCode.REASON_ARBITER_REJECTED,
            )

    def raw_cmd_callback(self, msg: VlnCommand):
        if not self._control_active or msg.episode_id != self.current_episode_id:
            self._publish_zero(msg.episode_id, msg.policy_sequence_id, "episode is not active")
            return

        stamp_sec = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9
        raw_data = TwistStampedData(
            header_stamp_sec=stamp_sec,
            linear_x=msg.twist.linear.x,
            angular_z=msg.twist.angular.z,
            frame_id="base_link",
        )

        self.current_seq_id = max(self.current_seq_id, msg.policy_sequence_id)
        safe_data, status_data = self.filter.filter_command(
            raw_cmd=raw_data,
            episode_id=self.current_episode_id,
            action_sequence_id=msg.policy_sequence_id,
            current_time_stamp_sec=(self.get_clock().now().nanoseconds * 1e-9),
        )

        self._publish_outputs(safe_data, status_data)

    def watchdog_timer_callback(self):
        if not self._control_active:
            return
        safe_data, status_data = self.filter.check_watchdog(
            episode_id=self.current_episode_id,
            action_seq_id=self.current_seq_id,
            current_time_stamp_sec=(self.get_clock().now().nanoseconds * 1e-9),
        )

        # If watchdog is tripped (timeout), actively publish zero-velocity command
        if status_data.policy_timeout:
            self._publish_outputs(safe_data, status_data)

    def _publish_zero(
        self,
        episode_id: str,
        sequence_id: int,
        reason: str,
        reason_code: ReasonCode = ReasonCode.REASON_EPISODE_INACTIVE,
    ):
        stamp = self.get_clock().now().to_msg()
        safe_data = TwistStampedData(
            header_stamp_sec=stamp.sec + stamp.nanosec * 1e-9,
            linear_x=0.0,
            angular_z=0.0,
        )
        status_data = SafetyStatusData(
            header_stamp_sec=safe_data.header_stamp_sec,
            episode_id=episode_id,
            action_sequence_id=sequence_id,
            command_accepted=False,
            command_modified=True,
            emergency_stop=self.filter.emergency_stop_active,
            policy_timeout=False,
            human_takeover=self.filter.human_takeover_active,
            reason_code=reason_code,
            reason_detail=reason,
        )
        self._publish_outputs(safe_data, status_data)

    def _publish_outputs(self, safe_data: TwistStampedData, status_data):
        now_time = self.get_clock().now().to_msg()

        # 1. Publish a context-preserving safe command envelope.
        safe_msg = VlnCommand()
        safe_msg.header.stamp.sec = int(safe_data.header_stamp_sec)
        safe_msg.header.stamp.nanosec = int(
            (safe_data.header_stamp_sec - int(safe_data.header_stamp_sec)) * 1e9
        )
        safe_msg.header.frame_id = "base_link"
        safe_msg.episode_id = status_data.episode_id
        safe_msg.policy_sequence_id = status_data.action_sequence_id
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
