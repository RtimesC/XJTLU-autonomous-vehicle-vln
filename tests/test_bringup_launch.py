"""Tests for vln_bringup configuration files and launch file syntax."""

import ast
import os
from pathlib import Path
import py_compile
CONFIG_PATH = Path(__file__).resolve().parent.parent / "src" / "vln_bringup" / "config" / "vln_params.yaml"
MOCK_LAUNCH_PATH = Path(__file__).resolve().parent.parent / "src" / "vln_bringup" / "launch" / "vln_mock_pipeline.launch.py"
SHADOW_LAUNCH_PATH = Path(__file__).resolve().parent.parent / "src" / "vln_bringup" / "launch" / "vln_shadow_mode.launch.py"


def parse_simple_yaml(file_path: Path):
    """Simple parser for flat/nested ROS 2 parameter YAMLs without third-party dependencies."""
    result = {}
    current_section = None
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if line.endswith(":\n") and not line.startswith(" "):
                current_section = stripped[:-1]
                result[current_section] = {}
            elif ":" in stripped and current_section:
                key, val = stripped.split(":", 1)
                val = val.strip().strip('"').strip("'")
                try:
                    if "." in val:
                        val = float(val)
                    else:
                        val = int(val)
                except ValueError:
                    pass
                result[current_section][key.strip()] = val
    return result


def test_vln_params_yaml_validity():
    assert CONFIG_PATH.exists(), f"Config file not found at {CONFIG_PATH}"
    data = parse_simple_yaml(CONFIG_PATH)

    # Check top-level nodes
    assert "vln_mock_policy_node" in data
    assert "vln_action_adapter" in data
    assert "vln_safety_node" in data

    # Check policy params
    policy_params = data["vln_mock_policy_node"]
    assert policy_params["frequency_hz"] > 0
    assert policy_params["steps_to_stop"] > 0
    assert 0.0 < policy_params["target_linear_velocity"] <= 1.0

    # Check adapter params
    adapter_params = data["vln_action_adapter"]
    assert 0.5 <= adapter_params["stop_threshold"] <= 1.0
    assert adapter_params["consecutive_stop_frames"] >= 2

    # Check safety params
    safety_params = data["vln_safety_node"]
    assert 0.0 < safety_params["max_linear_velocity"] <= 1.5
    assert safety_params["max_linear_accel"] > 0.0
    assert safety_params["watchdog_timeout_sec"] <= 0.5  # Meets the 300-500ms safety window


def test_launch_files_compile_and_have_entrypoint():
    for launch_file in [MOCK_LAUNCH_PATH, SHADOW_LAUNCH_PATH]:
        assert launch_file.exists(), f"Launch file not found: {launch_file}"

        # 1. Compile check (ensures clean python syntax)
        py_compile.compile(str(launch_file), doraise=True)

        # 2. AST inspection (ensures generate_launch_description function exists)
        with open(launch_file, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=str(launch_file))

        function_names = [
            node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
        ]
        assert "generate_launch_description" in function_names, (
            f"{launch_file.name} missing 'generate_launch_description'"
        )
