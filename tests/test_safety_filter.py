"""Unit tests for SafetyFilter constraints, watchdogs, and zeroing."""

import sys
import os
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src/vln_core")))

from vln_core.protocol import ReasonCode, TwistStampedData
from vln_core.safety_filter import SafetyFilter, SafetyFilterConfig


def test_velocity_clamping():
    config = SafetyFilterConfig(
        max_linear_velocity=0.8,
        min_linear_velocity=-0.2,
        max_angular_velocity=1.0,
        max_linear_accel=10.0,  # high to isolate velocity limit
        max_angular_accel=10.0,
    )
    f = SafetyFilter(config)

    raw_cmd = TwistStampedData(header_stamp_sec=100.0, linear_x=1.5, angular_z=2.5)
    safe_cmd, status = f.filter_command(raw_cmd, episode_id="ep_001", action_sequence_id=1, current_time_monotonic=1.0)

    assert safe_cmd.linear_x == pytest.approx(0.8)
    assert safe_cmd.angular_z == pytest.approx(1.0)
    assert status.command_modified is True
    assert status.reason_code == ReasonCode.REASON_SPEED_LIMIT


def test_acceleration_slew_rate():
    config = SafetyFilterConfig(
        max_linear_velocity=1.0,
        max_angular_velocity=1.0,
        max_linear_accel=0.5,   # max dv = 0.5 * 0.1 = 0.05 per 100ms
        max_angular_accel=1.0,
    )
    f = SafetyFilter(config)

    # Step 1 at t=1.0s, commanded vx=0.5 (from resting 0.0)
    # With nominal dt=0.1, max dv = 0.5 * 0.1 = 0.05
    raw_cmd = TwistStampedData(header_stamp_sec=100.0, linear_x=0.5, angular_z=0.0)
    safe_cmd, status = f.filter_command(raw_cmd, episode_id="ep_001", action_sequence_id=1, current_time_monotonic=1.0)

    assert safe_cmd.linear_x == pytest.approx(0.05)
    assert status.command_modified is True
    assert status.reason_code == ReasonCode.REASON_ACCELERATION_LIMIT

    # Step 2 at t=1.1s (dt=0.1s), commanded vx=0.5
    # Next allowed: 0.05 + 0.05 = 0.10
    safe_cmd2, _ = f.filter_command(raw_cmd, episode_id="ep_001", action_sequence_id=2, current_time_monotonic=1.1)
    assert safe_cmd2.linear_x == pytest.approx(0.10)


def test_watchdog_timeout_zeroing():
    config = SafetyFilterConfig(watchdog_timeout_sec=0.4)
    f = SafetyFilter(config)

    # Receive command at t=1.0s
    raw_cmd = TwistStampedData(header_stamp_sec=100.0, linear_x=0.5, angular_z=0.0)
    safe_cmd, status = f.filter_command(raw_cmd, episode_id="ep_001", action_sequence_id=1, current_time_monotonic=1.0)
    assert safe_cmd.linear_x > 0.0

    # Periodic watchdog check at t=1.2s (elapsed 0.2s <= 0.4s) -> still active
    safe_cmd_w1, status_w1 = f.check_watchdog(current_time_monotonic=1.2, episode_id="ep_001", action_seq_id=1)
    assert status_w1.policy_timeout is False

    # Periodic watchdog check at t=1.5s (elapsed 0.5s > 0.4s timeout!) -> trips!
    safe_cmd_w2, status_w2 = f.check_watchdog(current_time_monotonic=1.5, episode_id="ep_001", action_seq_id=1)
    assert status_w2.policy_timeout is True
    assert status_w2.reason_code == ReasonCode.REASON_POLICY_TIMEOUT
    assert safe_cmd_w2.linear_x == 0.0
    assert safe_cmd_w2.angular_z == 0.0


def test_emergency_stop_override():
    f = SafetyFilter()
    f.set_emergency_stop(True)

    raw_cmd = TwistStampedData(header_stamp_sec=100.0, linear_x=0.5, angular_z=0.2)
    safe_cmd, status = f.filter_command(raw_cmd, episode_id="ep_001", action_sequence_id=1, current_time_monotonic=1.0)

    assert safe_cmd.linear_x == 0.0
    assert safe_cmd.angular_z == 0.0
    assert status.emergency_stop is True
    assert status.reason_code == ReasonCode.REASON_EMERGENCY_STOP


def test_human_takeover_override():
    f = SafetyFilter()
    f.set_human_takeover(True)

    raw_cmd = TwistStampedData(header_stamp_sec=100.0, linear_x=0.5, angular_z=0.2)
    safe_cmd, status = f.filter_command(raw_cmd, episode_id="ep_001", action_sequence_id=1, current_time_monotonic=1.0)

    assert safe_cmd.linear_x == 0.0
    assert safe_cmd.angular_z == 0.0
    assert status.human_takeover is True
    assert status.reason_code == ReasonCode.REASON_HUMAN_TAKEOVER


def test_nan_command_rejection():
    f = SafetyFilter()
    raw_cmd = TwistStampedData(header_stamp_sec=100.0, linear_x=float("nan"), angular_z=0.0)
    safe_cmd, status = f.filter_command(raw_cmd, episode_id="ep_001", action_sequence_id=1, current_time_monotonic=1.0)

    assert safe_cmd.linear_x == 0.0
    assert safe_cmd.angular_z == 0.0
    assert status.command_accepted is False
    assert status.reason_code == ReasonCode.REASON_INVALID_ACTION


def test_stale_observation_is_rejected_when_ros_time_is_supplied():
    f = SafetyFilter(SafetyFilterConfig(max_action_age_sec=0.1, max_linear_accel=10.0))
    safe_cmd, status = f.filter_command(
        TwistStampedData(header_stamp_sec=10.0, linear_x=0.2, angular_z=0.0),
        episode_id="ep_001",
        action_sequence_id=1,
        current_time_monotonic=1.0,
        current_time_stamp_sec=10.2,
    )
    assert safe_cmd.linear_x == 0.0
    assert status.command_accepted is False
    assert status.reason_code == ReasonCode.REASON_ACTION_EXPIRED


def test_replayed_sequence_is_rejected():
    f = SafetyFilter(SafetyFilterConfig(max_linear_accel=10.0, max_angular_accel=10.0))
    f.filter_command(
        TwistStampedData(header_stamp_sec=10.0, linear_x=0.2, angular_z=0.0),
        episode_id="ep_001", action_sequence_id=2, current_time_monotonic=1.0,
    )
    safe_cmd, status = f.filter_command(
        TwistStampedData(header_stamp_sec=10.1, linear_x=0.2, angular_z=0.0),
        episode_id="ep_001", action_sequence_id=1, current_time_monotonic=1.1,
    )
    assert safe_cmd.linear_x == 0.0
    assert status.reason_code == ReasonCode.REASON_ACTION_EXPIRED
