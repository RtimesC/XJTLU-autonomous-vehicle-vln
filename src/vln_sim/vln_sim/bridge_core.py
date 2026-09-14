"""Core data structures and kinematic integration routines for simulation bridge."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
import math
from typing import Optional
import numpy as np


@dataclass
class SimAgentPose:
    """Agent 3D pose in simulator coordinates."""
    x: float = 0.0
    y: float = 0.0
    z: float = 0.45  # Height above ground in meters (matches vehicle camera mounting)
    yaw: float = 0.0  # Radians, 0 points forward along x-axis


@dataclass
class SimObservation:
    """Observation frame emitted by simulator."""
    rgb: np.ndarray  # Shape (H, W, 3), uint8
    timestamp_sec: float
    step_index: int
    depth: Optional[np.ndarray] = None


def integrate_differential_drive(
    pose: SimAgentPose,
    linear_velocity: float,
    angular_velocity: float,
    dt: float,
) -> SimAgentPose:
    """Integrates linear and angular velocities using unicycle kinematics.

    Args:
        pose: Current agent pose.
        linear_velocity: Forward velocity v (m/s).
        angular_velocity: Angular yaw rate w (rad/s).
        dt: Time delta (seconds).

    Returns:
        Updated SimAgentPose.
    """
    v = float(linear_velocity)
    w = float(angular_velocity)
    yaw = pose.yaw

    if abs(w) < 1e-5:
        # Straight line approximation
        dx = v * math.cos(yaw) * dt
        dy = v * math.sin(yaw) * dt
        new_yaw = yaw
    else:
        # Arc integration
        d_yaw = w * dt
        dx = (v / w) * (math.sin(yaw + d_yaw) - math.sin(yaw))
        dy = -(v / w) * (math.cos(yaw + d_yaw) - math.cos(yaw))
        new_yaw = yaw + d_yaw

    # Normalize yaw to [-pi, pi]
    normalized_yaw = math.atan2(math.sin(new_yaw), math.cos(new_yaw))

    return SimAgentPose(
        x=pose.x + dx,
        y=pose.y + dy,
        z=pose.z,
        yaw=normalized_yaw,
    )


class BaseSimAdapter(ABC):
    """Abstract interface for simulator backends (Habitat-Sim or MockScene)."""

    @abstractmethod
    def reset(self) -> SimObservation:
        """Resets simulator to initial scene state."""
        pass

    @abstractmethod
    def step(self, linear_velocity: float, angular_velocity: float, dt: float) -> SimObservation:
        """Advances simulation by dt using commanded velocities."""
        pass

    @abstractmethod
    def close(self) -> None:
        """Releases simulator resources."""
        pass
