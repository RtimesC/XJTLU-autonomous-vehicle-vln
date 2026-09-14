"""Unit tests for MockPolicy and pipeline integration with ActionAdapter and SafetyFilter."""

import os
import sys
import pytest

# Path setup
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src/vln_core")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src/vln_policy")))

from vln_core.protocol import validate_policy_action, ReasonCode
from vln_core.action_adapter import ActionAdapter, ActionAdapterConfig
from vln_core.safety_filter import SafetyFilter, SafetyFilterConfig
from vln_policy.mock_policy import MockPolicy, MockPolicyConfig


def test_mock_policy_cruising():
    config = MockPolicyConfig(
        target_linear_velocity=0.3,
        target_angular_velocity=0.05,
        steps_to_stop=10,
        history_length=3,
    )
    policy = MockPolicy(config=config)
    policy.reset(episode_id="test_ep_01", instruction="go straight")

    # Step 1
    action = policy.step(obs_stamp_sec=100.0)
    assert action.sequence_id == 1
    assert action.linear_velocity == pytest.approx(0.3)
    assert action.angular_velocity == pytest.approx(0.05)
    assert action.stop_probability < 0.1
    assert action.valid is True
    assert policy.is_goal_reached is False

    # Check contract validity
    is_valid, err = validate_policy_action(action, expected_episode_id="test_ep_01")
    assert is_valid is True
    assert err is None


def test_mock_policy_history_buffer():
    config = MockPolicyConfig(steps_to_stop=10, history_length=3)
    policy = MockPolicy(config=config)
    policy.reset("ep_01")

    for _ in range(5):
        policy.step()

    history = policy.action_history
    assert len(history) == 3
    # Check that entries are tuples of (v, w)
    assert isinstance(history[0], tuple)
    assert len(history[0]) == 2


def test_mock_policy_reaches_stop():
    config = MockPolicyConfig(steps_to_stop=4, stop_probability_active=0.98)
    policy = MockPolicy(config=config)
    policy.reset("ep_01")

    # Steps 1 to 3: cruising
    for _ in range(3):
        act = policy.step()
        assert act.stop_probability < 0.1

    assert policy.is_goal_reached is False

    # Step 4: reaches stop
    act4 = policy.step()
    assert act4.sequence_id == 4
    assert act4.stop_probability == pytest.approx(0.98)
    assert act4.linear_velocity == 0.0
    assert policy.is_goal_reached is True


def test_end_to_end_pipeline_integration():
    """Validates the full software loop: MockPolicy -> ActionAdapter -> SafetyFilter."""
    policy_config = MockPolicyConfig(
        target_linear_velocity=0.4,
        steps_to_stop=5,
        stop_probability_active=0.95,
    )
    policy = MockPolicy(config=policy_config)
    policy.reset("ep_pipeline_test")

    adapter = ActionAdapter(ActionAdapterConfig(stop_threshold=0.8, consecutive_stop_frames=2))
    adapter.reset_episode("ep_pipeline_test")

    safety = SafetyFilter(SafetyFilterConfig(max_linear_velocity=0.5, watchdog_timeout_sec=0.5))

    last_safe_cmd = None

    # Run for 15 steps:
    # Steps 1-4: cruising
    # Step 5: reached stop (p_stop >= 0.8, 1st frame)
    # Step 6: reached stop (p_stop >= 0.8, 2nd frame -> adapter latches stop, targets 0.0)
    # Steps 7-15: smooth deceleration ramp-down under acceleration limits until full stop
    for step_i in range(1, 16):
        t = 100.0 + step_i * 0.1
        # 1. Policy generates action
        action_data = policy.step(obs_stamp_sec=t)

        # 2. Adapter translates and checks stop probability
        twist_data, stop_triggered, detail = adapter.process_action(action_data)

        # 3. Safety filter checks limits, deceleration slew-rate, and freshness
        safe_cmd, status = safety.filter_command(
            raw_cmd=twist_data,
            episode_id=action_data.episode_id,
            action_sequence_id=action_data.sequence_id,
            current_time_monotonic=step_i * 0.1,
        )
        last_safe_cmd = safe_cmd

        if step_i < 5:
            # Cruising: speed should be moving forward
            assert safe_cmd.linear_x > 0.0
            assert adapter.is_stopped is False
        elif step_i >= 6:
            # Adapter must be latched stopped
            assert adapter.is_stopped is True

    # After sufficient ramp-down steps, final velocity must reach exactly 0.0
    assert last_safe_cmd.linear_x == pytest.approx(0.0)
    assert last_safe_cmd.angular_z == pytest.approx(0.0)
