"""Episode lifecycle manager component implementing NavigateLanguage semantics."""

from dataclasses import dataclass, field
from enum import Enum
import time
from typing import Dict, List, Optional, Tuple


class EpisodeState(str, Enum):
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


@dataclass
class EpisodeRecord:
    """Historical tracking for a single navigation episode."""
    episode_id: str
    instruction: str
    state: EpisodeState = EpisodeState.RUNNING
    start_time_monotonic: float = field(default_factory=time.monotonic)
    start_time_wall: float = field(default_factory=time.time)
    end_time_monotonic: Optional[float] = None
    termination_reason: str = "running"
    latest_sequence_id: int = 0
    latest_stop_probability: float = 0.0
    total_steps: int = 0
    completed: bool = False

    @property
    def elapsed_time_s(self) -> float:
        end = self.end_time_monotonic if self.end_time_monotonic is not None else time.monotonic()
        return max(0.0, end - self.start_time_monotonic)


@dataclass
class EpisodeManagerConfig:
    """Configuration for EpisodeManager."""
    max_duration_sec: float = 60.0
    max_steps: int = 500


class EpisodeManager:
    """Manages episode lifecycles and coordinates policy completion.

    Strict contract rules:
    - Enforces uniqueness of episode_id per experiment run.
    - Rejects concurrent goal requests without silently overwriting active runs.
    - Transitions to COMPLETED only upon policy p_stop latch.
    - Terminates cleanly upon client cancellation or maximum time limit.
    """

    def __init__(self, config: Optional[EpisodeManagerConfig] = None):
        self.config = config or EpisodeManagerConfig()
        self._active_record: Optional[EpisodeRecord] = None
        self._history: Dict[str, EpisodeRecord] = {}

    @property
    def is_running(self) -> bool:
        return self._active_record is not None and self._active_record.state == EpisodeState.RUNNING

    @property
    def active_record(self) -> Optional[EpisodeRecord]:
        return self._active_record

    @property
    def history(self) -> Dict[str, EpisodeRecord]:
        return dict(self._history)

    def start_episode(
        self,
        episode_id: str,
        instruction: str,
        monotonic_now: Optional[float] = None,
    ) -> Tuple[bool, str]:
        """Initiates a new episode."""
        if not episode_id or not episode_id.strip():
            return False, "Episode ID cannot be empty or blank."

        if self.is_running:
            return False, (
                f"Cannot start episode '{episode_id}': active episode "
                f"'{self._active_record.episode_id}' is already running."
            )

        if episode_id in self._history:
            return False, f"Episode ID '{episode_id}' has already been executed."

        now_mono = monotonic_now if monotonic_now is not None else time.monotonic()
        record = EpisodeRecord(
            episode_id=episode_id.strip(),
            instruction=instruction.strip(),
            start_time_monotonic=now_mono,
            start_time_wall=time.time(),
        )
        self._active_record = record
        self._history[record.episode_id] = record
        return True, f"Episode '{record.episode_id}' started."

    def update_action(
        self,
        sequence_id: int,
        stop_probability: float,
        is_latched_stopped: bool,
        monotonic_now: Optional[float] = None,
    ) -> Tuple[bool, str]:
        """Updates active episode with latest step outcomes.

        Returns:
            (is_finished, termination_reason)
        """
        if not self.is_running:
            return True, "No active episode running."

        rec = self._active_record
        rec.total_steps += 1
        rec.latest_sequence_id = sequence_id
        rec.latest_stop_probability = stop_probability

        now_mono = monotonic_now if monotonic_now is not None else time.monotonic()

        # 1. Check policy-triggered completion
        if is_latched_stopped:
            rec.state = EpisodeState.COMPLETED
            rec.completed = True
            rec.termination_reason = "policy_stop_latch"
            rec.end_time_monotonic = now_mono
            return True, rec.termination_reason

        # 2. Check maximum step limit
        if rec.total_steps >= self.config.max_steps:
            rec.state = EpisodeState.FAILED
            rec.completed = False
            rec.termination_reason = "max_steps_exceeded"
            rec.end_time_monotonic = now_mono
            return True, rec.termination_reason

        # 3. Check duration timeout
        if (now_mono - rec.start_time_monotonic) > self.config.max_duration_sec:
            rec.state = EpisodeState.FAILED
            rec.completed = False
            rec.termination_reason = "max_duration_timeout"
            rec.end_time_monotonic = now_mono
            return True, rec.termination_reason

        return False, "running"

    def cancel_episode(
        self,
        reason: str = "client_cancelled",
        monotonic_now: Optional[float] = None,
    ) -> Tuple[bool, str]:
        """Cancels the active episode."""
        if not self.is_running:
            return False, "No active episode to cancel."

        now_mono = monotonic_now if monotonic_now is not None else time.monotonic()
        rec = self._active_record
        rec.state = EpisodeState.CANCELLED
        rec.completed = False
        rec.termination_reason = reason
        rec.end_time_monotonic = now_mono
        return True, f"Episode '{rec.episode_id}' cancelled: {reason}"
