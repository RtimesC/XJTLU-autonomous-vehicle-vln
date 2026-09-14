"""Mock indoor scene simulator adapter for headless testing without Habitat binary."""

import time
import numpy as np

from .bridge_core import BaseSimAdapter, SimAgentPose, SimObservation, integrate_differential_drive


class MockSceneAdapter(BaseSimAdapter):
    """Synthetic indoor corridor simulator generating realistic test frames.

    Renders a procedural corridor view with walls, floor, ceiling, and doorway,
    responding dynamically to robot motion (translation and rotation).
    """

    def __init__(self, width: int = 640, height: int = 480):
        self.width = width
        self.height = height
        self.pose = SimAgentPose()
        self._step_counter = 0

    def reset(self) -> SimObservation:
        self.pose = SimAgentPose()
        self._step_counter = 0
        return self._render(time.time())

    def step(self, linear_velocity: float, angular_velocity: float, dt: float) -> SimObservation:
        self.pose = integrate_differential_drive(self.pose, linear_velocity, angular_velocity, dt)
        self._step_counter += 1
        return self._render(time.time())

    def close(self) -> None:
        pass

    def _render(self, timestamp: float) -> SimObservation:
        # Create a procedural synthetic corridor view
        img = np.zeros((self.height, self.width, 3), dtype=np.uint8)

        # Ceiling (dark gray)
        img[0 : self.height // 2, :] = [80, 80, 90]
        # Floor (light gray / tile)
        img[self.height // 2 :, :] = [160, 160, 170]

        # Perspective corridor vanishing point influenced by robot yaw
        cx = int(self.width / 2 - self.pose.yaw * (self.width / 2))
        cx = max(0, min(self.width - 1, cx))
        cy = self.height // 2

        # Draw left wall (bluish gray) and right wall (warm gray)
        for y in range(self.height):
            dy = abs(y - cy)
            left_bound = max(0, int(cx - dy * 1.2))
            right_bound = min(self.width, int(cx + dy * 1.2))
            img[y, :left_bound] = [120, 130, 140]
            img[y, right_bound:] = [140, 130, 120]

        # Draw a synthetic doorway in front of robot, scaling with forward distance (x)
        door_dist = max(0.5, 6.0 - self.pose.x)
        door_w = max(10, int(180 / door_dist))
        door_h = max(20, int(300 / door_dist))
        d_x1 = max(0, cx - door_w // 2)
        d_x2 = min(self.width, cx + door_w // 2)
        d_y1 = max(0, cy - door_h // 2)
        d_y2 = min(self.height, cy + door_h // 2)
        img[d_y1:d_y2, d_x1:d_x2] = [40, 60, 100]  # Dark door frame

        return SimObservation(
            rgb=img,
            timestamp_sec=timestamp,
            step_index=self._step_counter,
        )
