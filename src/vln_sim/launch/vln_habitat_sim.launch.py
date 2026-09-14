"""Launch file for complete Habitat simulation closed-loop pipeline."""

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
    # 1. Locate sim params
    sim_params_file = ""
    if get_package_share_directory is not None:
        try:
            pkg_share = get_package_share_directory('vln_sim')
            sim_params_file = os.path.join(pkg_share, 'config', 'sim_params.yaml')
        except Exception:
            pass
    if not sim_params_file or not os.path.exists(sim_params_file):
        sim_params_file = str(Path(__file__).resolve().parent.parent / 'config' / 'sim_params.yaml')

    # 2. Locate vln params
    vln_params_file = ""
    if get_package_share_directory is not None:
        try:
            vln_share = get_package_share_directory('vln_bringup')
            vln_params_file = os.path.join(vln_share, 'config', 'vln_params.yaml')
        except Exception:
            pass
    if not vln_params_file or not os.path.exists(vln_params_file):
        vln_params_file = str(
            Path(__file__).resolve().parent.parent.parent / 'vln_bringup' / 'config' / 'vln_params.yaml'
        )

    sim_params_arg = DeclareLaunchArgument(
        'sim_params_file',
        default_value=sim_params_file,
        description='Path to simulation parameters YAML file',
    )

    vln_params_arg = DeclareLaunchArgument(
        'vln_params_file',
        default_value=vln_params_file,
        description='Path to VLN stack parameters YAML file',
    )

    sim_backend_arg = DeclareLaunchArgument(
        'backend',
        default_value='auto',
        description="Simulation backend: 'auto' (prefers real Habitat if installed), 'habitat', or 'mock'",
    )

    notice = LogInfo(
        msg="[VLN HABITAT SIMULATION] Launching Habitat Bridge with closed-loop VLN policy and safety stack."
    )

    # Node 1: Habitat Bridge Node (virtual environment + virtual camera)
    bridge_node = Node(
        package='vln_sim',
        executable='vln_habitat_bridge_node',
        name='vln_habitat_bridge_node',
        output='screen',
        parameters=[LaunchConfiguration('sim_params_file'), {'backend': LaunchConfiguration('backend')}],
    )

    # Node 2: VLN Policy Node (in image_driven mode, consuming virtual camera)
    policy_node = Node(
        package='vln_policy',
        executable='vln_mock_policy_node',
        name='vln_mock_policy_node',
        output='screen',
        parameters=[LaunchConfiguration('vln_params_file'), {'mode': 'image_driven'}],
    )

    # Node 3: Action Adapter Node
    action_adapter_node = Node(
        package='vln_core',
        executable='vln_action_adapter_node',
        name='vln_action_adapter',
        output='screen',
        parameters=[LaunchConfiguration('vln_params_file')],
    )

    # Node 4: Safety Filter Node
    safety_node = Node(
        package='vln_core',
        executable='vln_safety_node',
        name='vln_safety_node',
        output='screen',
        parameters=[LaunchConfiguration('vln_params_file')],
    )

    return LaunchDescription([
        sim_params_arg,
        vln_params_arg,
        sim_backend_arg,
        notice,
        bridge_node,
        policy_node,
        action_adapter_node,
        safety_node,
    ])
