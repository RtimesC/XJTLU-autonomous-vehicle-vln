"""Unit tests for protocol data validation."""

import math
import pytest
import sys
import os

# Add src/vln_core to path for testing without installing
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src/vln_core")))

from vln_core.protocol import PolicyActionData, ReasonCode, validate_policy_action


def make_valid_action(**kwargs) -> PolicyActionData:
    defaults = {
        "header_stamp_sec": 1000.0,
        "episode_id": "ep_001",
        "sequence_id": 1,
        "linear_velocity": 0.4,
        "angular_velocity": 0.1,
        "stop_probability": 0.05,
        "inference_latency_ms": 45.0,
        "valid": True,
        "model_version": "baseline_v0.1_fp16",
    }
    defaults.update(kwargs)
    return PolicyActionData(**defaults)


def test_valid_policy_action():
    action = make_valid_action()
    is_valid, err = validate_policy_action(action, expected_episode_id="ep_001")
    assert is_valid is True
    assert err is None


def test_invalid_explicit_flag():
    action = make_valid_action(valid=False)
    is_valid, err = validate_policy_action(action)
    assert is_valid is False
    assert "explicitly set to false" in err


def test_nan_linear_velocity():
    action = make_valid_action(linear_velocity=float("nan"))
    is_valid, err = validate_policy_action(action)
    assert is_valid is False
    assert "NaN" in err


def test_inf_angular_velocity():
    action = make_valid_action(angular_velocity=float("inf"))
    is_valid, err = validate_policy_action(action)
    assert is_valid is False
    assert "Inf" in err


def test_out_of_bounds_stop_probability():
    action = make_valid_action(stop_probability=1.2)
    is_valid, err = validate_policy_action(action)
    assert is_valid is False
    assert "out of bounds" in err

    action2 = make_valid_action(stop_probability=-0.01)
    is_valid2, err2 = validate_policy_action(action2)
    assert is_valid2 is False
    assert "out of bounds" in err2


def test_episode_id_mismatch():
    action = make_valid_action(episode_id="ep_002")
    is_valid, err = validate_policy_action(action, expected_episode_id="ep_001")
    assert is_valid is False
    assert "mismatch" in err


def test_empty_model_version():
    action = make_valid_action(model_version="  ")
    is_valid, err = validate_policy_action(action)
    assert is_valid is False
    assert "model_version" in err
