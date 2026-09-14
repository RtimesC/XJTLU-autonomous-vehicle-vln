"""ROS 2 node bridging Habitat simulation with the VLN stack."""

import sys
import time
from typing import Optional
import numpy as np

try:
    import rclpy
    from rclpy.node import Node
    from sensor_msgs.msg import Image
    from vln_interfaces.msg import VlnCommand
except ImportError:
    rclpy = None
    Node = object
    Image = None
    VlnCommand = None

from vln_sim.bridge_core import BaseSimAdapter
from vln_sim.mock_scene_adapter import MockSceneAdapter
from vln_sim.habitat_adapter import HabitatSimAdapter, habitat_sim


class VlnHabitatBridgeNode(Node if rclpy else object):
    """Bridges simulation environment (Habitat or MockScene) with /vln topics."""

    def __init__(self):
        if rclpy is None:
            raise RuntimeError("rclpy is not installed; cannot initialize VlnHabitatBridgeNode")
        super().__init__('vln_habitat_bridge_node')

        # Parameters
        self.declare_parameter('backend', 'auto')  # 'auto', 'habitat', or 'mock'
        self.declare_parameter('scene_path', 'data/scene_datasets/habitat-test-scenes/skokloster-castle.glb')
        self.declare_parameter('image_width', 640)
        self.declare_parameter('image_height', 480)
        self.declare_parameter('sensor_height', 0.45)
        self.declare_parameter('hfov', 90.0)
        self.declare_parameter('step_rate_hz', 10.0)
        self.declare_parameter('watchdog_timeout_sec', 0.5)

        backend = self.get_parameter('backend').get_parameter_value().string_value
        scene_path = self.get_parameter('scene_path').get_parameter_value().string_value
        width = self.get_parameter('image_width').get_parameter_value().integer_value
        height = self.get_parameter('image_height').get_parameter_value().integer_value
        sensor_height = self.get_parameter('sensor_height').get_parameter_value().double_value
        hfov = self.get_parameter('hfov').get_parameter_value().double_value
        self.rate_hz = self.get_parameter('step_rate_hz').get_parameter_value().double_value
        self.watchdog_sec = self.get_parameter('watchdog_timeout_sec').get_parameter_value().double_value

        # Initialize backend adapter
        self.adapter: BaseSimAdapter
        if backend == 'habitat' or (backend == 'auto' and habitat_sim is not None):
            self.get_logger().info(f"Initializing real HabitatSimAdapter (scene={scene_path})")
            self.adapter = HabitatSimAdapter(
                scene_path=scene_path,
                width=width,
                height=height,
                sensor_height=sensor_height,
                hfov=hfov,
            )
        else:
            self.get_logger().info("Initializing MockSceneAdapter (synthetic corridor simulator)")
            self.adapter = MockSceneAdapter(width=width, height=height)

        # Publishers
        qos_sensor = rclpy.qos.QoSProfile(
            reliability=rclpy.qos.ReliabilityPolicy.BEST_EFFORT,
            history=rclpy.qos.HistoryPolicy.KEEP_LAST,
            depth=1,
        )
        self.image_pub = self.create_publisher(Image, '/vln/input/image', qos_sensor)

        # Subscribers
        qos_cmd = rclpy.qos.QoSProfile(
            reliability=rclpy.qos.ReliabilityPolicy.RELIABLE,
            history=rclpy.qos.HistoryPolicy.KEEP_LAST,
            depth=1,
        )
        self.cmd_sub = self.create_subscription(
            VlnCommand,
            '/vln/safe_cmd_vel',
            self.cmd_callback,
            qos_cmd,
        )

        # Simulation state
        self._target_v: float = 0.0
        self._target_w: float = 0.0
        self._last_cmd_monotonic: Optional[float] = None
        self._last_step_monotonic: float = time.monotonic()

        # Step timer
        period = 1.0 / max(1.0, self.rate_hz)
        self.timer = self.create_wall_timer(period, self.sim_step_callback)
        self.adapter.reset()

        self.get_logger().info(
            f"vln_habitat_bridge_node started ({self.rate_hz} Hz, {width}x{height})"
        )

    def cmd_callback(self, msg: VlnCommand):
        self._target_v = msg.twist.linear.x
        self._target_w = msg.twist.angular.z
        self._last_cmd_monotonic = time.monotonic()

    def sim_step_callback(self):
        now_mono = time.monotonic()
        dt = max(0.001, now_mono - self._last_step_monotonic)
        self._last_step_monotonic = now_mono

        # Watchdog: if no command received recently, command zero velocity
        v = self._target_v
        w = self._target_w
        if self._last_cmd_monotonic is None or (now_mono - self._last_cmd_monotonic) > self.watchdog_sec:
            v = 0.0
            w = 0.0

        # Step the simulator
        obs = self.adapter.step(linear_velocity=v, angular_velocity=w, dt=dt)

        # Convert numpy RGB to ROS Image message
        img_msg = Image()
        img_msg.header.stamp = self.get_clock().now().to_msg()
        img_msg.header.frame_id = "camera_color_optical_frame"
        img_msg.height = obs.rgb.shape[0]
        img_msg.width = obs.rgb.shape[1]
        img_msg.encoding = "rgb8"
        img_msg.is_bigendian = 0
        img_msg.step = obs.rgb.shape[1] * 3
        img_msg.data = obs.rgb.tobytes()

        self.image_pub.publish(img_msg)

    def destroy_node(self):
        if hasattr(self, 'adapter') and self.adapter:
            self.adapter.close()
        super().destroy_node()


def main(args=None):
    if rclpy is None:
        print("Error: rclpy not available on this system.", file=sys.stderr)
        return 1
    rclpy.init(args=args)
    node = VlnHabitatBridgeNode()
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
