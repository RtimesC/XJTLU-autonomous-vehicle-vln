"""Unit tests for ActionAdapter stopping semantics and latching."""

import sys
import os
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src/vln_core")))

from vln_core.action_adapter import ActionAdapter, ActionAdapterConfig
from vln_core.protocol import PolicyActionData, PolicyOutcome


def make_action(seq: int, v: float = 0.5, w: float = 0.0, p_stop: float = 0.1, ep: str = "ep_001") -> PolicyActionData:
    return PolicyActionData(
        header_stamp_sec=100.0 + seq * 0.1,
        episode_id=ep,
        sequence_id=seq,
        linear_velocity=v,
        angular_velocity=w,
        stop_probability=p_stop,
        inference_latency_ms=30.0,
        valid=True,
        model_version="test_v1",
    )


def test_action_adapter_normal_flow():
    adapter = ActionAdapter(ActionAdapterConfig(stop_threshold=0.8, consecutive_stop_frames=3))
    adapter.reset_episode("ep_001")

    act = make_action(seq=1, v=0.4, w=0.2, p_stop=0.1)
    twist, stop_triggered, detail = adapter.process_action(act)

    assert twist.linear_x == pytest.approx(0.4)
    assert twist.angular_z == pytest.approx(0.2)
    assert stop_triggered is False
    assert adapter.is_stopped is False


def test_stop_latching_and_zero_enforcement():
    adapter = ActionAdapter(ActionAdapterConfig(stop_threshold=0.8, consecutive_stop_frames=3))
    adapter.reset_episode("ep_001")

    # Frame 1: high stop prob
    twist, stopped, _ = adapter.process_action(make_action(seq=1, v=0.5, p_stop=0.85))
    assert stopped is False
    assert twist.linear_x == pytest.approx(0.5)

    # Frame 2: high stop prob
    twist, stopped, _ = adapter.process_action(make_action(seq=2, v=0.5, p_stop=0.90))
    assert stopped is False
    assert twist.linear_x == pytest.approx(0.5)

    # Frame 3: high stop prob -> trigger!
    twist, stopped, _ = adapter.process_action(make_action(seq=3, v=0.5, p_stop=0.95))
    assert stopped is True
    assert adapter.is_stopped is True
    assert twist.linear_x == 0.0
    assert twist.angular_z == 0.0

    # Frame 4: policy tries to resume forward motion with low p_stop
    twist, stopped, detail = adapter.process_action(make_action(seq=4, v=0.5, p_stop=0.01))
    assert stopped is False
    assert adapter.is_stopped is True
    assert twist.linear_x == 0.0
    assert twist.angular_z == 0.0
    assert "latched stopped" in detail


def test_consecutive_reset_on_intermittent_drop():
    adapter = ActionAdapter(ActionAdapterConfig(stop_threshold=0.8, consecutive_stop_frames=3))
    adapter.reset_episode("ep_001")

    # Frame 1 & 2 high
    adapter.process_action(make_action(seq=1, p_stop=0.85))
    adapter.process_action(make_action(seq=2, p_stop=0.85))

    # Frame 3 dips below threshold
    adapter.process_action(make_action(seq=3, p_stop=0.4))
    assert adapter.is_stopped is False

    # Frame 4 & 5 high -> not 3 consecutive yet
    adapter.process_action(make_action(seq=4, p_stop=0.85))
    twist, stopped, _ = adapter.process_action(make_action(seq=5, p_stop=0.85))
    assert stopped is False
    assert adapter.is_stopped is False

    # Frame 6 high -> 3rd consecutive since dip -> trigger!
    twist, stopped, _ = adapter.process_action(make_action(seq=6, p_stop=0.85))
    assert stopped is True
    assert adapter.is_stopped is True


def test_reset_episode():
    adapter = ActionAdapter(ActionAdapterConfig(stop_threshold=0.8, consecutive_stop_frames=2))
    adapter.reset_episode("ep_001")

    adapter.process_action(make_action(seq=1, p_stop=0.9))
    adapter.process_action(make_action(seq=2, p_stop=0.9))
    assert adapter.is_stopped is True

    # Start new episode
    adapter.reset_episode("ep_002")
    assert adapter.is_stopped is False
    twist, stopped, _ = adapter.process_action(make_action(seq=1, v=0.3, p_stop=0.1, ep="ep_002"))
    assert twist.linear_x == pytest.approx(0.3)
    assert stopped is False


def test_policy_failure_does_not_trigger_success_stop():
    adapter = ActionAdapter()
    adapter.reset_episode("ep_failed")
    failure = make_action(seq=1, v=0.0, p_stop=0.0, ep="ep_failed")
    failure.outcome = PolicyOutcome.FAILED
    failure.outcome_detail = "search exhausted"
    twist, stopped, detail = adapter.process_action(failure)
    assert twist.linear_x == 0.0
    assert stopped is False
    assert adapter.is_stopped is False
    assert "failure" in detail
