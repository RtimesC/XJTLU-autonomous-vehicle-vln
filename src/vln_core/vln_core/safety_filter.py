"""Safety filter component: velocity clamping, acceleration limits, watchdog timeouts, and zero-velocity enforcement."""

from dataclasses import dataclass
import math
import time
from typing import Optional, Tuple

from .protocol import ReasonCode, SafetyStatusData, TwistStampedData


@dataclass
class SafetyFilterConfig:
    """Configuration parameters for SafetyFilter."""
    max_linear_velocity: float = 0.8        # m/s
    min_linear_velocity: float = -0.2       # m/s (allow slight reverse or 0.0)
    max_angular_velocity: float = 1.0       # rad/s
    max_linear_accel: float = 0.8           # m/s^2
    max_angular_accel: float = 1.5          # rad/s^2
    watchdog_timeout_sec: float = 0.4       # 400 ms timeout window
    max_action_age_sec: float = 0.5         # 500 ms max observation age


class SafetyFilter:
    """Enforces safety limits, watchdogs, and emergency zeroing on raw commands.

    Strict rules:
    - Never generates obstacle avoidance paths or alters heading directions.
    - Strictly limits velocity and acceleration bounds.
    - Monitors monotonic action freshness and observation timestamps.
    - Actively forces continuous zero velocities upon timeout, emergency stop,
      or human takeover.
    """

    def __init__(self, config: Optional[SafetyFilterConfig] = None):
        self.config = config or SafetyFilterConfig()
        self._last_cmd_time_monotonic: Optional[float] = None
        self._last_linear_x: float = 0.0
        self._last_angular_z: float = 0.0
        self._last_stamp_sec: float = 0.0
        self._last_action_sequence_id: Optional[int] = None

        # Safety trip flags
        self._emergency_stop: bool = False
        self._human_takeover: bool = False
        self._arbiter_denied: bool = False

    def reset(self, preserve_overrides: bool = False) -> None:
        """Resets command memory, optionally retaining external safety trips."""
        emergency_stop = self._emergency_stop
        human_takeover = self._human_takeover
        arbiter_denied = self._arbiter_denied
        self._last_cmd_time_monotonic = None
        self._last_linear_x = 0.0
        self._last_angular_z = 0.0
        self._last_stamp_sec = 0.0
        self._last_action_sequence_id = None
        self._emergency_stop = emergency_stop if preserve_overrides else False
        self._human_takeover = human_takeover if preserve_overrides else False
        self._arbiter_denied = arbiter_denied if preserve_overrides else False

    def set_emergency_stop(self, active: bool) -> None:
        self._emergency_stop = active

    def set_human_takeover(self, active: bool) -> None:
        self._human_takeover = active

    def set_arbiter_denied(self, active: bool) -> None:
        self._arbiter_denied = active

    @property
    def emergency_stop_active(self) -> bool:
        return self._emergency_stop

    @property
    def human_takeover_active(self) -> bool:
        return self._human_takeover

    def check_watchdog(
        self,
        current_time_monotonic: Optional[float] = None,
        episode_id: str = "default_episode",
        action_seq_id: int = 0,
        current_time_stamp_sec: Optional[float] = None,
    ) -> Tuple[TwistStampedData, SafetyStatusData]:
        """Periodic watchdog check.

        If no fresh command arrived within watchdog_timeout_sec,
        forces an active zero-velocity output and emits a timeout status.
        """
        now_mono = current_time_monotonic if current_time_monotonic is not None else time.monotonic()
        now_stamp = current_time_stamp_sec if current_time_stamp_sec is not None else time.time()

        is_timeout = False
        if self._last_cmd_time_monotonic is None:
            is_timeout = True
            reason_detail = "Watchdog: no action has been received yet."
        elif (now_mono - self._last_cmd_time_monotonic) > self.config.watchdog_timeout_sec:
            is_timeout = True
            elapsed_ms = (now_mono - self._last_cmd_time_monotonic) * 1000.0
            reason_detail = (
                f"Watchdog: policy action timed out ({elapsed_ms:.1f} ms > "
                f"{self.config.watchdog_timeout_sec * 1000.0:.1f} ms)."
            )
        else:
            reason_detail = "Watchdog: active"

        if is_timeout:
            self._last_linear_x = 0.0
            self._last_angular_z = 0.0
            safe_cmd = TwistStampedData(header_stamp_sec=now_stamp, linear_x=0.0, angular_z=0.0)
            status = SafetyStatusData(
                header_stamp_sec=now_stamp,
                episode_id=episode_id,
                action_sequence_id=action_seq_id,
                command_accepted=False,
                command_modified=True,
                emergency_stop=self._emergency_stop,
                policy_timeout=True,
                human_takeover=self._human_takeover,
                reason_code=ReasonCode.REASON_POLICY_TIMEOUT,
                reason_detail=reason_detail,
            )
            return safe_cmd, status

        # Still within timeout window: maintain last safe command
        safe_cmd = TwistStampedData(
            header_stamp_sec=self._last_stamp_sec,
            linear_x=self._last_linear_x,
            angular_z=self._last_angular_z,
        )
        status = SafetyStatusData(
            header_stamp_sec=now_stamp,
            episode_id=episode_id,
            action_sequence_id=action_seq_id,
            command_accepted=True,
            command_modified=False,
            emergency_stop=self._emergency_stop,
            policy_timeout=False,
            human_takeover=self._human_takeover,
            reason_code=ReasonCode.REASON_NORMAL,
            reason_detail="Command within watchdog window",
        )
        return safe_cmd, status

    def filter_command(
        self,
        raw_cmd: TwistStampedData,
        episode_id: str,
        action_sequence_id: int,
        current_time_monotonic: Optional[float] = None,
        current_time_stamp_sec: Optional[float] = None,
    ) -> Tuple[TwistStampedData, SafetyStatusData]:
        """Applies limits, acceleration smoothing, age verification, and safety trip checks.

        Returns:
            (safe_cmd, safety_status)
        """
        now_mono = current_time_monotonic if current_time_monotonic is not None else time.monotonic()
        stamp = raw_cmd.header_stamp_sec

        # 1. External override trips (Emergency stop, takeover, arbiter)
        if self._emergency_stop:
            self._last_linear_x = 0.0
            self._last_angular_z = 0.0
            return (
                TwistStampedData(header_stamp_sec=stamp, linear_x=0.0, angular_z=0.0),
                SafetyStatusData(
                    header_stamp_sec=stamp,
                    episode_id=episode_id,
                    action_sequence_id=action_sequence_id,
                    command_accepted=False,
                    command_modified=True,
                    emergency_stop=True,
                    policy_timeout=False,
                    human_takeover=self._human_takeover,
                    reason_code=ReasonCode.REASON_EMERGENCY_STOP,
                    reason_detail="Emergency stop active. Command zeroed.",
                ),
            )

        if self._human_takeover:
            self._last_linear_x = 0.0
            self._last_angular_z = 0.0
            return (
                TwistStampedData(header_stamp_sec=stamp, linear_x=0.0, angular_z=0.0),
                SafetyStatusData(
                    header_stamp_sec=stamp,
                    episode_id=episode_id,
                    action_sequence_id=action_sequence_id,
                    command_accepted=False,
                    command_modified=True,
                    emergency_stop=False,
                    policy_timeout=False,
                    human_takeover=True,
                    reason_code=ReasonCode.REASON_HUMAN_TAKEOVER,
                    reason_detail="Human takeover active. Command zeroed.",
                ),
            )

        if self._arbiter_denied:
            self._last_linear_x = 0.0
            self._last_angular_z = 0.0
            return (
                TwistStampedData(header_stamp_sec=stamp, linear_x=0.0, angular_z=0.0),
                SafetyStatusData(
                    header_stamp_sec=stamp,
                    episode_id=episode_id,
                    action_sequence_id=action_sequence_id,
                    command_accepted=False,
                    command_modified=True,
                    emergency_stop=False,
                    policy_timeout=False,
                    human_takeover=False,
                    reason_code=ReasonCode.REASON_ARBITER_REJECTED,
                    reason_detail="Control arbiter rejected VLN control. Command zeroed.",
                ),
            )

        # 2. NaN / Inf checks
        if math.isnan(raw_cmd.linear_x) or math.isinf(raw_cmd.linear_x) or \
           math.isnan(raw_cmd.angular_z) or math.isinf(raw_cmd.angular_z):
            self._last_linear_x = 0.0
            self._last_angular_z = 0.0
            return (
                TwistStampedData(header_stamp_sec=stamp, linear_x=0.0, angular_z=0.0),
                SafetyStatusData(
                    header_stamp_sec=stamp,
                    episode_id=episode_id,
                    action_sequence_id=action_sequence_id,
                    command_accepted=False,
                    command_modified=True,
                    emergency_stop=False,
                    policy_timeout=False,
                    human_takeover=False,
                    reason_code=ReasonCode.REASON_INVALID_ACTION,
                    reason_detail="NaN or Inf detected in raw command velocity.",
                ),
            )

        # Reject replayed or reordered actions before they can refresh the
        # watchdog. The adapter performs the same check at the policy boundary;
        # keeping it here protects the command boundary independently.
        if (
            self._last_action_sequence_id is not None
            and action_sequence_id <= self._last_action_sequence_id
        ):
            self._last_linear_x = 0.0
            self._last_angular_z = 0.0
            return (
                TwistStampedData(header_stamp_sec=stamp, linear_x=0.0, angular_z=0.0),
                SafetyStatusData(
                    header_stamp_sec=stamp,
                    episode_id=episode_id,
                    action_sequence_id=action_sequence_id,
                    command_accepted=False,
                    command_modified=True,
                    emergency_stop=False,
                    policy_timeout=False,
                    human_takeover=False,
                    reason_code=ReasonCode.REASON_ACTION_EXPIRED,
                    reason_detail=(
                        f"Out-of-order action sequence {action_sequence_id}; "
                        f"last accepted sequence was {self._last_action_sequence_id}."
                    ),
                ),
            )

        # Observation timestamps and the local monotonic clock are different
        # domains. The ROS node supplies the current ROS timestamp explicitly;
        # omitting it keeps the standalone deterministic API usable in tests.
        if current_time_stamp_sec is not None:
            action_age = current_time_stamp_sec - stamp
            if action_age > self.config.max_action_age_sec or action_age < 0.0:
                self._last_linear_x = 0.0
                self._last_angular_z = 0.0
                return (
                    TwistStampedData(header_stamp_sec=stamp, linear_x=0.0, angular_z=0.0),
                    SafetyStatusData(
                        header_stamp_sec=stamp,
                        episode_id=episode_id,
                        action_sequence_id=action_sequence_id,
                        command_accepted=False,
                        command_modified=True,
                        emergency_stop=False,
                        policy_timeout=False,
                        human_takeover=False,
                        reason_code=ReasonCode.REASON_ACTION_EXPIRED,
                        reason_detail=f"Action observation age is {action_age * 1000.0:.1f} ms.",
                    ),
                )

        # 3. Time freshness & dt calculation
        dt = 0.1  # default nominal dt if first step
        if self._last_cmd_time_monotonic is not None:
            dt = max(0.001, now_mono - self._last_cmd_time_monotonic)

        self._last_cmd_time_monotonic = now_mono
        self._last_action_sequence_id = action_sequence_id

        target_vx = raw_cmd.linear_x
        target_wz = raw_cmd.angular_z
        modified = False
        reasons = []

        # 4. Velocity magnitude clamping
        clamped_vx = max(self.config.min_linear_velocity, min(self.config.max_linear_velocity, target_vx))
        if clamped_vx != target_vx:
            modified = True
            reasons.append(
                f"Speed clamped: requested linear_x={target_vx:.3f} -> {clamped_vx:.3f}"
            )
            target_vx = clamped_vx

        clamped_wz = max(-self.config.max_angular_velocity, min(self.config.max_angular_velocity, target_wz))
        if clamped_wz != target_wz:
            modified = True
            reasons.append(
                f"Yaw rate clamped: requested angular_z={target_wz:.3f} -> {clamped_wz:.3f}"
            )
            target_wz = clamped_wz

        # 5. Acceleration slew-rate limits
        max_dv = self.config.max_linear_accel * dt
        dv = target_vx - self._last_linear_x
        if abs(dv) > max_dv:
            limited_vx = self._last_linear_x + math.copysign(max_dv, dv)
            modified = True
            reasons.append(
                f"Linear accel limited: target={target_vx:.3f} -> {limited_vx:.3f} (max dv={max_dv:.3f})"
            )
            target_vx = limited_vx

        max_dw = self.config.max_angular_accel * dt
        dw = target_wz - self._last_angular_z
        if abs(dw) > max_dw:
            limited_wz = self._last_angular_z + math.copysign(max_dw, dw)
            modified = True
            reasons.append(
                f"Angular accel limited: target={target_wz:.3f} -> {limited_wz:.3f} (max dw={max_dw:.3f})"
            )
            target_wz = limited_wz

        self._last_linear_x = target_vx
        self._last_angular_z = target_wz
        self._last_stamp_sec = stamp

        if modified:
            reason_code = (
                ReasonCode.REASON_ACCELERATION_LIMIT
                if "accel" in "".join(reasons).lower()
                else ReasonCode.REASON_SPEED_LIMIT
            )
            detail = "; ".join(reasons)
        else:
            reason_code = ReasonCode.REASON_NORMAL
            detail = "Command accepted without modification."

        safe_cmd = TwistStampedData(header_stamp_sec=stamp, linear_x=target_vx, angular_z=target_wz)
        status = SafetyStatusData(
            header_stamp_sec=stamp,
            episode_id=episode_id,
            action_sequence_id=action_sequence_id,
            command_accepted=True,
            command_modified=modified,
            emergency_stop=False,
            policy_timeout=False,
            human_takeover=False,
            reason_code=reason_code,
            reason_detail=detail,
        )
        return safe_cmd, status
