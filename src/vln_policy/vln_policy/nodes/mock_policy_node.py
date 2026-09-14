"""ROS 2 Node running MockPolicy."""

import sys
from typing import Optional

try:
    import rclpy
    from rclpy.node import Node
    from sensor_msgs.msg import Image
    from vln_interfaces.msg import EpisodeControl, PolicyAction
except ImportError:
    rclpy = None
    Node = object
    Image = None
    EpisodeControl = None
    PolicyAction = None

from vln_policy.mock_policy import MockPolicy, MockPolicyConfig


class VlnMockPolicyNode(Node if rclpy else object):
    """ROS 2 Node executing mock VLN inference and emitting /vln/policy_action."""

    def __init__(self):
        if rclpy is None:
            raise RuntimeError("rclpy is not installed; cannot initialize VlnMockPolicyNode")
        super().__init__('vln_mock_policy_node')

        # Declare parameters
        self.declare_parameter('mode', 'timer')  # 'timer' or 'image_driven'
        self.declare_parameter('frequency_hz', 10.0)
        self.declare_parameter('target_linear_velocity', 0.35)
        self.declare_parameter('target_angular_velocity', 0.0)
        self.declare_parameter('steps_to_stop', 30)
        self.declare_parameter('episode_id', 'ep_mock_001')
        self.declare_parameter('instruction', 'go straight for 3 seconds then stop')
        self.declare_parameter('autostart', False)

        mode = self.get_parameter('mode').get_parameter_value().string_value
        freq = self.get_parameter('frequency_hz').get_parameter_value().double_value
        target_v = self.get_parameter('target_linear_velocity').get_parameter_value().double_value
        target_w = self.get_parameter('target_angular_velocity').get_parameter_value().double_value
        steps_stop = self.get_parameter('steps_to_stop').get_parameter_value().integer_value
        ep_id = self.get_parameter('episode_id').get_parameter_value().string_value
        instruction = self.get_parameter('instruction').get_parameter_value().string_value

        config = MockPolicyConfig(
            target_linear_velocity=target_v,
            target_angular_velocity=target_w,
            steps_to_stop=steps_stop,
        )
        self.policy = MockPolicy(config=config)
        self.policy.reset(episode_id=ep_id, instruction=instruction)

        # Publisher for policy actions
        qos_profile = rclpy.qos.QoSProfile(
            reliability=rclpy.qos.ReliabilityPolicy.RELIABLE,
            history=rclpy.qos.HistoryPolicy.KEEP_LAST,
            depth=1,
        )
        self.action_pub = self.create_publisher(
            PolicyAction,
            '/vln/policy_action',
            qos_profile,
        )

        self._active = self.get_parameter('autostart').get_parameter_value().bool_value
        # Episode manager is the only source of episode identity and instruction.
        qos_control = rclpy.qos.QoSProfile(
            reliability=rclpy.qos.ReliabilityPolicy.RELIABLE,
            durability=rclpy.qos.DurabilityPolicy.TRANSIENT_LOCAL,
            history=rclpy.qos.HistoryPolicy.KEEP_LAST,
            depth=1,
        )
        self.instruction_sub = self.create_subscription(
            EpisodeControl,
            '/vln/episode_control',
            self.control_callback,
            qos_control,
        )

        self.mode = mode
        if mode == 'timer':
            period = 1.0 / max(0.1, freq)
            self.timer = self.create_wall_timer(period, self.timer_callback)
            self.get_logger().info(f"MockPolicy running in autonomous TIMER mode ({freq} Hz)")
        else:
            # Image driven mode
            qos_sensor = rclpy.qos.QoSProfile(
                reliability=rclpy.qos.ReliabilityPolicy.BEST_EFFORT,
                history=rclpy.qos.HistoryPolicy.KEEP_LAST,
                depth=1,
            )
            self.image_sub = self.create_subscription(
                Image,
                '/vln/input/image',
                self.image_callback,
                qos_sensor,
            )
            self.get_logger().info("MockPolicy running in IMAGE_DRIVEN mode (waiting for /vln/input/image)")

    def control_callback(self, msg: EpisodeControl):
        if msg.command == EpisodeControl.COMMAND_START:
            self.policy.reset(episode_id=msg.episode_id, instruction=msg.instruction)
            self._active = True
            self.get_logger().info(f"Started episode '{msg.episode_id}'.")
        elif msg.episode_id == self.policy.episode_id:
            self._active = False
            self.get_logger().info(f"Stopped episode '{msg.episode_id}': {msg.reason}")

    def timer_callback(self):
        if not self._active:
            return
        now_msg = self.get_clock().now().to_msg()
        stamp_sec = now_msg.sec + now_msg.nanosec * 1e-9

        action_data = self.policy.step(obs_stamp_sec=stamp_sec)
        self._publish_action(action_data, now_msg)

    def image_callback(self, msg: Image):
        if not self._active:
            return
        stamp_sec = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9
        action_data = self.policy.step(obs_stamp_sec=stamp_sec)
        self._publish_action(action_data, msg.header.stamp)

    def _publish_action(self, action_data, stamp_msg):
        out_msg = PolicyAction()
        out_msg.header.stamp = stamp_msg
        out_msg.header.frame_id = "base_link"
        out_msg.episode_id = action_data.episode_id
        out_msg.sequence_id = action_data.sequence_id
        out_msg.linear_velocity = float(action_data.linear_velocity)
        out_msg.angular_velocity = float(action_data.angular_velocity)
        out_msg.stop_probability = float(action_data.stop_probability)
        out_msg.inference_latency_ms = float(action_data.inference_latency_ms)
        out_msg.valid = bool(action_data.valid)
        out_msg.model_version = str(action_data.model_version)
        out_msg.outcome = int(action_data.outcome)
        out_msg.outcome_detail = str(action_data.outcome_detail)

        self.action_pub.publish(out_msg)


def main(args=None):
    if rclpy is None:
        print("Error: rclpy not available on this system.", file=sys.stderr)
        return 1
    rclpy.init(args=args)
    node = VlnMockPolicyNode()
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
