"""ROS 2 Node running ReactiveDoorNavPolicy on live or simulated images."""

import sys
import numpy as np

try:
    import rclpy
    from rclpy.node import Node
    from sensor_msgs.msg import Image
    from std_msgs.msg import String
    from vln_interfaces.msg import PolicyAction
except ImportError:
    rclpy = None
    Node = object
    Image = None
    String = None
    PolicyAction = None

from vln_policy.door_nav_policy import ReactiveDoorNavPolicy, ReactiveDoorNavConfig


class VlnDoorNavPolicyNode(Node if rclpy else object):
    """ROS 2 Node executing real-time visual DoorNav B1 inference on /vln/input/image."""

    def __init__(self):
        if rclpy is None:
            raise RuntimeError("rclpy is not installed; cannot initialize VlnDoorNavPolicyNode")
        super().__init__('vln_door_nav_policy_node')

        # Declare parameters
        self.declare_parameter('episode_id', 'doornav_ep_001')
        self.declare_parameter('instruction', 'find and approach doorway')
        self.declare_parameter('approach_velocity', 0.35)
        self.declare_parameter('arrival_area_threshold', 0.18)

        ep_id = self.get_parameter('episode_id').get_parameter_value().string_value
        instruction = self.get_parameter('instruction').get_parameter_value().string_value
        v_approach = self.get_parameter('approach_velocity').get_parameter_value().double_value
        area_thresh = self.get_parameter('arrival_area_threshold').get_parameter_value().double_value

        config = ReactiveDoorNavConfig(
            approach_linear_velocity=v_approach,
            arrival_area_ratio_threshold=area_thresh,
        )
        self.policy = ReactiveDoorNavPolicy(config=config)
        self.policy.reset(episode_id=ep_id, instruction=instruction)

        # QoS
        qos_sensor = rclpy.qos.QoSProfile(
            reliability=rclpy.qos.ReliabilityPolicy.BEST_EFFORT,
            history=rclpy.qos.HistoryPolicy.KEEP_LAST,
            depth=1,
        )
        qos_action = rclpy.qos.QoSProfile(
            reliability=rclpy.qos.ReliabilityPolicy.RELIABLE,
            history=rclpy.qos.HistoryPolicy.KEEP_LAST,
            depth=1,
        )

        self.image_sub = self.create_subscription(
            Image,
            '/vln/input/image',
            self.image_callback,
            qos_sensor,
        )

        self.action_pub = self.create_publisher(
            PolicyAction,
            '/vln/policy_action',
            qos_action,
        )

        self.instruction_sub = self.create_subscription(
            String,
            '/vln/goal_instruction',
            self.instruction_callback,
            10,
        )

        self.get_logger().info(
            f"vln_door_nav_policy_node initialized (target_v={v_approach} m/s, "
            f"area_thresh={area_thresh}, waiting for /vln/input/image)"
        )

    def instruction_callback(self, msg: String):
        new_ep = f"ep_{int(self.get_clock().now().nanoseconds // 1e6)}"
        self.get_logger().info(f"Received new instruction: '{msg.data}'. Resetting episode {new_ep}.")
        self.policy.reset(episode_id=new_ep, instruction=msg.data)

    def image_callback(self, msg: Image):
        stamp_sec = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9

        # Convert Image message to numpy RGB array
        try:
            h, w = msg.height, msg.width
            if msg.encoding in ("rgb8", "bgr8"):
                img_np = np.frombuffer(msg.data, dtype=np.uint8).reshape((h, w, 3))
                if msg.encoding == "bgr8":
                    img_np = img_np[:, :, ::-1]  # Convert BGR to RGB
            elif msg.encoding == "mono8":
                gray = np.frombuffer(msg.data, dtype=np.uint8).reshape((h, w))
                img_np = np.stack([gray, gray, gray], axis=-1)
            else:
                self.get_logger().warn(f"Unsupported image encoding: {msg.encoding}")
                return
        except Exception as exc:
            self.get_logger().error(f"Image decode error: {exc}")
            return

        # Policy inference
        action_data = self.policy.predict(img_np, obs_stamp_sec=stamp_sec)

        # Publish PolicyAction
        out_msg = PolicyAction()
        out_msg.header.stamp = msg.header.stamp
        out_msg.header.frame_id = "base_link"
        out_msg.episode_id = action_data.episode_id
        out_msg.sequence_id = action_data.sequence_id
        out_msg.linear_velocity = float(action_data.linear_velocity)
        out_msg.angular_velocity = float(action_data.angular_velocity)
        out_msg.stop_probability = float(action_data.stop_probability)
        out_msg.inference_latency_ms = float(action_data.inference_latency_ms)
        out_msg.valid = bool(action_data.valid)
        out_msg.model_version = str(action_data.model_version)

        self.action_pub.publish(out_msg)


def main(args=None):
    if rclpy is None:
        print("Error: rclpy not available on this system.", file=sys.stderr)
        return 1
    rclpy.init(args=args)
    node = VlnDoorNavPolicyNode()
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
