"""Mock policy implementation for testing the end-to-end data pipeline."""

from collections import deque
from dataclasses import dataclass, field
import time
from typing import Deque, List, Optional, Tuple

import sys
import os
# Ensure vln_core is importable
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../vln_core")))
from vln_core.protocol import PolicyActionData, PolicyOutcome


@dataclass
class MockPolicyConfig:
    """Configuration parameters for MockPolicy."""
    target_linear_velocity: float = 0.35      # m/s
    target_angular_velocity: float = 0.0     # rad/s
    steps_to_stop: int = 30                  # Stop after 30 steps
    stop_probability_active: float = 0.95    # Stop probability when stopping
    stop_probability_cruising: float = 0.02  # Stop probability while cruising
    simulated_latency_ms: float = 35.0       # Simulated forward pass latency
    history_length: int = 5                  # Number of past actions to track
    model_version: str = "mock_scripted_v0.1"


class MockPolicy:
    """Mock/Dummy VLN policy generating predictable trajectories and stop decisions.

    Adheres strictly to the main experiment boundary:
    - Only relies on simulated visual observation events, instruction, and action history.
    - Does NOT access SLAM, TF, map, GPS, or Nav2 costs.
    - Generates strictly contract-compliant PolicyActionData objects.
    """

    def __init__(self, config: Optional[MockPolicyConfig] = None):
        self.config = config or MockPolicyConfig()
        self._current_episode_id: str = "mock_episode_0"
        self._current_instruction: str = "navigate straight and stop"
        self._step_counter: int = 0
        self._action_history: Deque[Tuple[float, float]] = deque(maxlen=self.config.history_length)

    @property
    def episode_id(self) -> str:
        return self._current_episode_id

    @property
    def instruction(self) -> str:
        return self._current_instruction

    @property
    def current_step(self) -> int:
        return self._step_counter

    @property
    def action_history(self) -> List[Tuple[float, float]]:
        return list(self._action_history)

    @property
    def is_goal_reached(self) -> bool:
        return self._step_counter >= self.config.steps_to_stop

    def reset(self, episode_id: str, instruction: str = "navigate straight and stop") -> None:
        """Resets the policy state for a new episode."""
        self._current_episode_id = episode_id
        self._current_instruction = instruction
        self._step_counter = 0
        self._action_history.clear()

    def step(
        self,
        obs_stamp_sec: Optional[float] = None,
        image_data: Optional[bytes] = None,
    ) -> PolicyActionData:
        """Performs one step of policy prediction.

        Returns:
            PolicyActionData adhering to ros_interface_contract.md.
        """
        self._step_counter += 1
        stamp = obs_stamp_sec if obs_stamp_sec is not None else time.time()

        if self._step_counter >= self.config.steps_to_stop:
            # Reached destination: command stop
            v = 0.0
            w = 0.0
            p_stop = self.config.stop_probability_active
            outcome = PolicyOutcome.STOP_REQUESTED
        else:
            # Cruising towards destination
            v = self.config.target_linear_velocity
            w = self.config.target_angular_velocity
            p_stop = self.config.stop_probability_cruising
            outcome = PolicyOutcome.RUNNING

        # Record action in history
        self._action_history.append((v, w))

        return PolicyActionData(
            header_stamp_sec=stamp,
            frame_id="base_link",
            episode_id=self._current_episode_id,
            sequence_id=self._step_counter,
            linear_velocity=float(v),
            angular_velocity=float(w),
            stop_probability=float(p_stop),
            inference_latency_ms=float(self.config.simulated_latency_ms),
            valid=True,
            model_version=self.config.model_version,
            outcome=outcome,
        )
