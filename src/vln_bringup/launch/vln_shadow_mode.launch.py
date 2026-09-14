"""Launch file for running VLN in Shadow Mode (silent observer, no chassis actuation)."""

import os
from pathlib import Path

try:
    from ament_index_python.packages import get_package_share_directory
    from launch import LaunchDescription
    from launch.actions import DeclareLaunchArgument, LogInfo
    from launch.substitutions import LaunchConfiguration
    from launch_ros.actions import Node
except ImportError:
    LaunchDescription = None
    DeclareLaunchArgument = None
    LaunchConfiguration = None
    LogInfo = None
    Node = None
    get_package_share_directory = None


def generate_launch_description():
    default_params_file = ""
    if get_package_share_directory is not None:
        try:
            pkg_share = get_package_share_directory('vln_bringup')
            default_params_file = os.path.join(pkg_share, 'config', 'vln_params.yaml')
        except Exception:
            pass

    if not default_params_file or not os.path.exists(default_params_file):
        default_params_file = str(Path(__file__).resolve().parent.parent / 'config' / 'vln_params.yaml')

    params_arg = DeclareLaunchArgument(
        'params_file',
        default_value=default_params_file,
        description='Full path to the ROS 2 parameters YAML file',
    )

    camera_topic_arg = DeclareLaunchArgument(
        'camera_topic',
        default_value='/camera/color/image_raw',
        description='Physical camera topic name to remap to /vln/input/image',
    )

    safety_notice = LogInfo(
        msg="[SHADOW MODE ACTIVE] VLN is running in silent observation mode. "
            "Outputs are recorded to /vln/* and will NOT be forwarded to /cmd_vel."
    )

    # 1. Policy Node (in image_driven mode)
    policy_node = Node(
        package='vln_policy',
        executable='vln_mock_policy_node',
        name='vln_mock_policy_node',
        output='screen',
        parameters=[LaunchConfiguration('params_file'), {'mode': 'image_driven'}],
        remappings=[('/vln/input/image', LaunchConfiguration('camera_topic'))],
    )

    # 2. Action Adapter Node
    action_adapter_node = Node(
        package='vln_core',
        executable='vln_action_adapter_node',
        name='vln_action_adapter',
        output='screen',
        parameters=[LaunchConfiguration('params_file')],
    )

    # 3. Safety Filter Node
    safety_node = Node(
        package='vln_core',
        executable='vln_safety_node',
        name='vln_safety_node',
        output='screen',
        parameters=[LaunchConfiguration('params_file')],
    )

    return LaunchDescription([
        params_arg,
        camera_topic_arg,
        safety_notice,
        policy_node,
        action_adapter_node,
        safety_node,
    ])
