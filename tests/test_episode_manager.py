"""Unit tests for EpisodeManager in vln_core."""

import sys
import os
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src/vln_core")))

from vln_core.episode_manager import (
    EpisodeManager,
    EpisodeManagerConfig,
    EpisodeState,
)


def test_start_episode_success():
    manager = EpisodeManager()
    assert not manager.is_running
    assert manager.active_record is None

    ok, reason = manager.start_episode(
        episode_id="ep_001",
        instruction="Navigate through the open blue door",
        monotonic_now=100.0,
    )
    assert ok
    assert "started" in reason
    assert manager.is_running
    assert manager.active_record is not None
    assert manager.active_record.episode_id == "ep_001"
    assert manager.active_record.state == EpisodeState.RUNNING
    assert "ep_001" in manager.history


def test_reject_blank_or_duplicate_or_concurrent():
    manager = EpisodeManager()

    # Empty ID
    ok, err = manager.start_episode("", "go forward")
    assert not ok
    assert "empty" in err.lower()

    # Valid start
    ok, _ = manager.start_episode("ep_101", "go forward", monotonic_now=10.0)
    assert ok

    # Concurrent start attempt
    ok2, err2 = manager.start_episode("ep_102", "go back", monotonic_now=11.0)
    assert not ok2
    assert "already running" in err2.lower()

    # Finish ep_101
    manager.update_action(1, 1.0, is_latched_stopped=True, monotonic_now=12.0)
    assert not manager.is_running

    # Re-use ep_101 ID attempt
    ok3, err3 = manager.start_episode("ep_101", "go again", monotonic_now=13.0)
    assert not ok3
    assert "already been executed" in err3.lower()


def test_policy_stop_latch_completion():
    manager = EpisodeManager()
    manager.start_episode("ep_latch", "reach the door", monotonic_now=10.0)

    # Step 1: not stopped
    finished, reason = manager.update_action(
        sequence_id=1,
        stop_probability=0.1,
        is_latched_stopped=False,
        monotonic_now=10.1,
    )
    assert not finished
    assert reason == "running"
    assert manager.active_record.total_steps == 1

    # Step 2: policy latches stop
    finished, reason = manager.update_action(
        sequence_id=2,
        stop_probability=0.95,
        is_latched_stopped=True,
        monotonic_now=10.2,
    )
    assert finished
    assert reason == "policy_stop_latch"
    assert manager.active_record.state == EpisodeState.COMPLETED
    assert manager.active_record.completed is True
    assert not manager.is_running


def test_max_steps_exceeded():
    cfg = EpisodeManagerConfig(max_steps=3)
    manager = EpisodeManager(config=cfg)
    manager.start_episode("ep_steps", "step test", monotonic_now=0.0)

    manager.update_action(1, 0.0, False, monotonic_now=1.0)
    manager.update_action(2, 0.0, False, monotonic_now=2.0)
    finished, reason = manager.update_action(3, 0.0, False, monotonic_now=3.0)

    assert finished
    assert reason == "max_steps_exceeded"
    assert manager.active_record.state == EpisodeState.FAILED
    assert manager.active_record.completed is False
    assert not manager.is_running


def test_duration_timeout():
    cfg = EpisodeManagerConfig(max_duration_sec=5.0)
    manager = EpisodeManager(config=cfg)
    manager.start_episode("ep_timeout", "timeout test", monotonic_now=100.0)

    # At 104s (within 5s)
    finished, _ = manager.update_action(1, 0.0, False, monotonic_now=104.0)
    assert not finished

    # At 106s (> 5s limit)
    finished, reason = manager.update_action(2, 0.0, False, monotonic_now=106.0)
    assert finished
    assert reason == "max_duration_timeout"
    assert manager.active_record.state == EpisodeState.FAILED


def test_client_cancellation():
    manager = EpisodeManager()
    # Cancel without active episode
    ok, _ = manager.cancel_episode()
    assert not ok

    manager.start_episode("ep_cancel", "cancel me", monotonic_now=10.0)
    ok, msg = manager.cancel_episode(reason="operator_e_stop", monotonic_now=12.0)
    assert ok
    assert "cancelled" in msg.lower()
    assert manager.active_record.state == EpisodeState.CANCELLED
    assert manager.active_record.termination_reason == "operator_e_stop"
    assert not manager.is_running


def test_policy_failure_is_not_completion():
    manager = EpisodeManager()
    manager.start_episode("ep_failed", "fail me", monotonic_now=1.0)
    finished, reason = manager.fail_episode("policy_failed", monotonic_now=1.5)
    assert finished is True
    assert reason == "policy_failed"
    assert manager.active_record.state == EpisodeState.FAILED
    assert manager.active_record.completed is False
