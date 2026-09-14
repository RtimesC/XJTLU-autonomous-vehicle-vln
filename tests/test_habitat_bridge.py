"""Unit tests for Habitat simulation bridge, kinematics, and launch files."""

import ast
import math
import os
from pathlib import Path
import py_compile
import sys
import numpy as np
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src/vln_sim")))

from vln_sim.bridge_core import SimAgentPose, integrate_differential_drive
from vln_sim.mock_scene_adapter import MockSceneAdapter


def test_kinematic_straight_line():
    init_pose = SimAgentPose(x=0.0, y=0.0, z=0.45, yaw=0.0)
    # 1.0 m/s for 0.5s -> dx = 0.5m
    next_pose = integrate_differential_drive(init_pose, linear_velocity=1.0, angular_velocity=0.0, dt=0.5)

    assert next_pose.x == pytest.approx(0.5)
    assert next_pose.y == pytest.approx(0.0)
    assert next_pose.yaw == pytest.approx(0.0)


def test_kinematic_pure_rotation():
    init_pose = SimAgentPose(x=0.0, y=0.0, z=0.45, yaw=0.0)
    # w = pi/2 rad/s for 1.0s -> dyaw = pi/2
    next_pose = integrate_differential_drive(init_pose, linear_velocity=0.0, angular_velocity=math.pi / 2, dt=1.0)

    assert next_pose.x == pytest.approx(0.0)
    assert next_pose.y == pytest.approx(0.0)
    assert next_pose.yaw == pytest.approx(math.pi / 2)


def test_kinematic_yaw_normalization():
    init_pose = SimAgentPose(yaw=math.pi - 0.1)
    # Rotate by +0.3 rad -> wraps past +pi to negative side
    next_pose = integrate_differential_drive(init_pose, linear_velocity=0.0, angular_velocity=0.3, dt=1.0)

    assert -math.pi <= next_pose.yaw <= math.pi
    assert next_pose.yaw == pytest.approx(-math.pi + 0.2)


def test_mock_scene_adapter_rendering():
    adapter = MockSceneAdapter(width=320, height=240)
    obs = adapter.reset()

    assert obs.rgb.shape == (240, 320, 3)
    assert obs.rgb.dtype == np.uint8
    assert obs.step_index == 0

    # Step forward
    obs2 = adapter.step(linear_velocity=0.5, angular_velocity=0.1, dt=0.1)
    assert obs2.step_index == 1
    assert adapter.pose.x > 0.0
    assert adapter.pose.yaw > 0.0


def test_sim_launch_file_compiles():
    launch_path = (
        Path(__file__).resolve().parent.parent / "src" / "vln_sim" / "launch" / "vln_habitat_sim.launch.py"
    )
    assert launch_path.exists(), f"Launch file not found: {launch_path}"

    py_compile.compile(str(launch_path), doraise=True)

    with open(launch_path, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=str(launch_path))

    function_names = [node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]
    assert "generate_launch_description" in function_names
