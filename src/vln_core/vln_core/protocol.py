"""Protocol definitions, data classes, and validation routines for VLN interfaces."""

from dataclasses import dataclass
from enum import IntEnum
import math
from typing import Optional, Tuple


class ReasonCode(IntEnum):
    """Reason codes aligned with vln_interfaces/msg/SafetyStatus.msg."""
    REASON_NORMAL = 0
    REASON_SPEED_LIMIT = 1
    REASON_ACCELERATION_LIMIT = 2
    REASON_INVALID_ACTION = 3
    REASON_ACTION_EXPIRED = 4
    REASON_POLICY_TIMEOUT = 5
    REASON_OBSTACLE_STOP = 6
    REASON_HUMAN_TAKEOVER = 7
    REASON_ARBITER_REJECTED = 8
    REASON_INTERNAL_ERROR = 9


@dataclass
class PolicyActionData:
    """Python representation of vln_interfaces/msg/PolicyAction.msg."""
    header_stamp_sec: float
    episode_id: str
    sequence_id: int
    linear_velocity: float
    angular_velocity: float
    stop_probability: float
    inference_latency_ms: float
    valid: bool
    model_version: str
    frame_id: str = "base_link"


@dataclass
class SafetyStatusData:
    """Python representation of vln_interfaces/msg/SafetyStatus.msg."""
    header_stamp_sec: float
    episode_id: str
    action_sequence_id: int
    command_accepted: bool
    command_modified: bool
    emergency_stop: bool
    policy_timeout: bool
    human_takeover: bool
    reason_code: ReasonCode
    reason_detail: str


@dataclass
class TwistStampedData:
    """Python representation of geometry_msgs/msg/TwistStamped."""
    header_stamp_sec: float
    linear_x: float
    angular_z: float
    frame_id: str = "base_link"


def validate_policy_action(
    action: PolicyActionData,
    expected_episode_id: Optional[str] = None
) -> Tuple[bool, Optional[str]]:
    """Strictly validates PolicyActionData fields against contract rules.

    Returns:
        (is_valid, reason_detail_if_invalid)
    """
    if not action.valid:
        return False, "action.valid is explicitly set to false by policy"

    if expected_episode_id is not None and action.episode_id != expected_episode_id:
        return False, (
            f"episode_id mismatch: expected '{expected_episode_id}', got '{action.episode_id}'"
        )

    if not action.episode_id or not action.episode_id.strip():
        return False, "episode_id is empty or whitespace"

    if action.sequence_id < 0:
        return False, f"negative sequence_id: {action.sequence_id}"

    for name, val in [
        ("linear_velocity", action.linear_velocity),
        ("angular_velocity", action.angular_velocity),
        ("stop_probability", action.stop_probability),
        ("inference_latency_ms", action.inference_latency_ms),
        ("header_stamp_sec", action.header_stamp_sec),
    ]:
        if math.isnan(val):
            return False, f"NaN value in field '{name}'"
        if math.isinf(val):
            return False, f"Inf value in field '{name}'"

    if action.inference_latency_ms < 0.0:
        return False, f"negative inference_latency_ms: {action.inference_latency_ms}"

    if not (0.0 <= action.stop_probability <= 1.0):
        return False, f"stop_probability out of bounds [0, 1]: {action.stop_probability}"

    if not action.model_version or not action.model_version.strip():
        return False, "model_version cannot be empty"

    return True, None
