"""Platform-neutral data contracts for one navigation episode.

These types deliberately avoid a camera SDK, VLM provider, ROS message, or
vehicle-specific velocity unit. Those choices belong in adapters.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class PlatformMode(str, Enum):
    HUMAN_CARRIED = "human_carried"
    MOBILE_BASE = "mobile_base"


class IntentType(str, Enum):
    OBSERVE = "observe"
    ADVANCE = "advance"
    INSPECT = "inspect"
    STOP = "stop"


class MotionOwner(str, Enum):
    NONE = "none"
    CAMERA = "camera"
    BODY = "body"
    MOBILE_BASE = "mobile_base"
    GIMBAL = "gimbal"


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class Goal:
    type: str
    value: str


@dataclass(slots=True)
class DepthSummary:
    front_distance_m: float | None = None
    left_distance_m: float | None = None
    right_distance_m: float | None = None
    target_distance_m: float | None = None
    valid_fraction: float | None = None


@dataclass(slots=True)
class Observation:
    step_id: int
    rgb_path: str | None
    depth_path: str | None
    depth_summary: DepthSummary
    platform_mode: PlatformMode
    observed_at: datetime = field(default_factory=now_utc)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class NavigationIntent:
    intent: IntentType
    motion_owner: MotionOwner
    target: str | None
    instruction: str
    completion_condition: str
    direction: str | None = None
    distance_hint: str | None = None
    speed_level: str | None = None
    stop: bool = False
    reason: str | None = None
    confidence: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> list[str]:
        """Return human-readable validation errors without choosing platform details."""
        errors: list[str] = []
        if not self.instruction.strip():
            errors.append("instruction must not be empty")
        if not self.completion_condition.strip():
            errors.append("completion_condition must not be empty")
        if self.intent is IntentType.STOP and not self.stop:
            errors.append("STOP intent must set stop=true")
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            errors.append("confidence must be between 0 and 1")
        if self.motion_owner is MotionOwner.NONE and self.intent is not IntentType.STOP:
            errors.append("a non-STOP intent needs a motion owner")
        return errors


@dataclass(slots=True)
class ExecutionResult:
    status: str
    actual_result: str
    operator_note: str = ""
    completed_at: datetime = field(default_factory=now_utc)


@dataclass(slots=True)
class StepRecord:
    observation: Observation
    intent: NavigationIntent
    execution: ExecutionResult | None = None
    memory_updates: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class EpisodeState:
    episode_id: str
    goal: Goal
    platform_mode: PlatformMode
    status: str = "searching"
    current_step: int = 0
    memory: list[dict[str, Any]] = field(default_factory=list)
    records: list[StepRecord] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the state into JSON-compatible values."""
        return _jsonable(asdict(self))


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value
