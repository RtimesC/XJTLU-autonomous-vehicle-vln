"""Mock indoor scene simulator adapter for headless testing without Habitat binary."""

import time
from typing import Optional
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

    def reset(self, init_pose: Optional[SimAgentPose] = None) -> SimObservation:
        self.pose = init_pose if init_pose is not None else SimAgentPose()
        self._step_counter = 0
        return self._render(time.time())

    def step(self, linear_velocity: float, angular_velocity: float, dt: float) -> SimObservation:
        self.pose = integrate_differential_drive(self.pose, linear_velocity, angular_velocity, dt)
        self._step_counter += 1
        return self._render(time.time())

    def close(self) -> None:
        pass

    def _render(self, timestamp: float) -> SimObservation:
        # Create a procedural synthetic indoor corridor view
        img = np.full((self.height, self.width, 3), 200, dtype=np.uint8)  # End corridor wall

        # Ceiling
        ceil_h = int(self.height * 0.15)
        img[:ceil_h, :] = [75, 75, 80]

        # Floor
        floor_y = int(self.height * 0.75)
        img[floor_y:, :] = [140, 140, 145]

        # Perspective corridor vanishing point influenced by robot yaw
        # In camera coordinates, when robot yaw > 0 (turned left), doorway appears to the right
        cx = int(self.width / 2 + self.pose.yaw * (self.width / 2))
        cx = max(0, min(self.width - 1, cx))
        cy = self.height // 2

        # Draw left wall and right wall
        for y in range(self.height):
            dy = abs(y - cy)
            left_bound = max(0, int(cx - dy * 1.3))
            right_bound = min(self.width, int(cx + dy * 1.3))
            if left_bound > 0:
                img[y, :left_bound] = [130, 135, 145]
            if right_bound < self.width:
                img[y, right_bound:] = [145, 135, 130]

        # Draw a synthetic doorway in front of robot, scaling with forward distance (x)
        door_dist = max(0.4, 4.0 - self.pose.x)
        door_w = max(20, int(220 / door_dist))
        door_h = max(40, int(420 / door_dist))

        d_x1 = max(0, cx - door_w // 2)
        d_x2 = min(self.width, cx + door_w // 2)
        d_y2 = min(self.height, floor_y)
        d_y1 = max(ceil_h, d_y2 - door_h)

        if d_x2 > d_x1 and d_y2 > d_y1:
            # Dark doorway interior
            img[d_y1:d_y2, d_x1:d_x2] = [35, 35, 45]
            # High-contrast door frame border
            border_thick = max(2, int(6 / door_dist))
            img[d_y1 : min(d_y2, d_y1 + border_thick), d_x1:d_x2] = [15, 15, 20]
            img[d_y1:d_y2, d_x1 : min(d_x2, d_x1 + border_thick)] = [15, 15, 20]
            img[d_y1:d_y2, max(d_x1, d_x2 - border_thick) : d_x2] = [15, 15, 20]

        return SimObservation(
            rgb=img,
            timestamp_sec=timestamp,
            step_index=self._step_counter,
        )
