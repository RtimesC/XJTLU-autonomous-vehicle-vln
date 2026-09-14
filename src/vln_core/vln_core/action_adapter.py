"""Action adapter component: translates PolicyAction into TwistStamped candidates and enforces stop latching."""

from dataclasses import dataclass
from typing import Optional, Tuple

from .protocol import PolicyActionData, PolicyOutcome, TwistStampedData, validate_policy_action


@dataclass
class ActionAdapterConfig:
    """Configuration for ActionAdapter."""
    stop_threshold: float = 0.8
    consecutive_stop_frames: int = 3


class ActionAdapter:
    """Adapts PolicyAction messages to candidate TwistStamped velocities.

    Enforces contract stopping semantics:
    - Tracks consecutive frames where stop_probability >= stop_threshold.
    - Once the stop threshold and consecutive frame count are reached, latches
      the stop state for the current episode.
    - Immediately outputs zero velocities upon stop.
    - Strictly prevents subsequent non-zero actions from resuming motion
      within the same episode.
    """

    def __init__(self, config: Optional[ActionAdapterConfig] = None):
        self.config = config or ActionAdapterConfig()
        self._current_episode_id: Optional[str] = None
        self._consecutive_stop_count: int = 0
        self._is_latched_stopped: bool = False
        self._total_actions_processed: int = 0
        self._last_sequence_id: Optional[int] = None

    @property
    def is_stopped(self) -> bool:
        """Returns whether this adapter is currently latched in the stopped state."""
        return self._is_latched_stopped

    @property
    def current_episode_id(self) -> Optional[str]:
        return self._current_episode_id

    def reset_episode(self, episode_id: str) -> None:
        """Resets the state for a new episode."""
        self._current_episode_id = episode_id
        self._consecutive_stop_count = 0
        self._is_latched_stopped = False
        self._total_actions_processed = 0
        self._last_sequence_id = None

    def process_action(
        self,
        action: PolicyActionData,
        expected_episode_id: Optional[str] = None,
    ) -> Tuple[TwistStampedData, bool, Optional[str]]:
        """Processes an incoming PolicyActionData.

        Returns:
            (raw_twist_stamped, is_stop_triggered_now, status_detail)
        """
        # Auto-initialize episode if none active
        if self._current_episode_id is None:
            self._current_episode_id = action.episode_id

        check_episode = expected_episode_id or self._current_episode_id
        is_valid, validation_error = validate_policy_action(action, expected_episode_id=check_episode)

        stamp = action.header_stamp_sec
        self._total_actions_processed += 1

        # If already latched stopped, refuse any motion
        if self._is_latched_stopped:
            return (
                TwistStampedData(header_stamp_sec=stamp, linear_x=0.0, angular_z=0.0),
                False,
                "Episode already latched stopped. Holding zero velocity.",
            )

        if not is_valid:
            return (
                TwistStampedData(header_stamp_sec=stamp, linear_x=0.0, angular_z=0.0),
                False,
                f"Invalid policy action rejected: {validation_error}",
            )

        if self._last_sequence_id is not None and action.sequence_id <= self._last_sequence_id:
            return (
                TwistStampedData(header_stamp_sec=stamp, linear_x=0.0, angular_z=0.0),
                False,
                f"Out-of-order policy action rejected: sequence_id={action.sequence_id} "
                f"after {self._last_sequence_id}.",
            )
        self._last_sequence_id = action.sequence_id

        if action.outcome == PolicyOutcome.FAILED:
            return (
                TwistStampedData(header_stamp_sec=stamp, linear_x=0.0, angular_z=0.0),
                False,
                f"Policy reported failure: {action.outcome_detail or 'unspecified failure'}",
            )

        # Check stopping probability
        if action.stop_probability >= self.config.stop_threshold:
            self._consecutive_stop_count += 1
        else:
            self._consecutive_stop_count = 0

        # Check if stop condition met
        if self._consecutive_stop_count >= self.config.consecutive_stop_frames:
            self._is_latched_stopped = True
            return (
                TwistStampedData(header_stamp_sec=stamp, linear_x=0.0, angular_z=0.0),
                True,
                f"Stop triggered by policy (p_stop >= {self.config.stop_threshold} for "
                f"{self.config.consecutive_stop_frames} consecutive frames).",
            )

        # Normal candidate velocity passthrough
        return (
            TwistStampedData(
                header_stamp_sec=stamp,
                linear_x=float(action.linear_velocity),
                angular_z=float(action.angular_velocity),
            ),
            False,
            "Normal action adapted",
        )
