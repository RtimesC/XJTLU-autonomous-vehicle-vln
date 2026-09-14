"""Real Habitat-Sim adapter wrapping habitat_sim.Simulator."""

import os
import time
from typing import Optional
import numpy as np

from .bridge_core import BaseSimAdapter, SimAgentPose, SimObservation, integrate_differential_drive

try:
    import habitat_sim
except ImportError:
    habitat_sim = None


class HabitatSimAdapter(BaseSimAdapter):
    """Adapter interfacing directly with Facebook AI Habitat-Sim."""

    def __init__(
        self,
        scene_path: str,
        width: int = 640,
        height: int = 480,
        hfov: float = 90.0,
        sensor_height: float = 0.45,
    ):
        if habitat_sim is None:
            raise RuntimeError(
                "habitat_sim is not installed in the active environment. "
                "Please install habitat-sim (via conda install habitat-sim withbullet -c aihabitat) "
                "or use MockSceneAdapter."
            )

        self.scene_path = scene_path
        self.width = width
        self.height = height
        self.hfov = hfov
        self.sensor_height = sensor_height

        self._sim = None
        self._step_counter = 0
        self.pose = SimAgentPose(z=sensor_height)
        self._init_sim()

    def _init_sim(self):
        backend_cfg = habitat_sim.SimulatorConfiguration()
        backend_cfg.scene_id = self.scene_path
        backend_cfg.enable_physics = False

        # Visual camera sensor (matching physical car camera height 0.45m)
        camera_sensor_spec = habitat_sim.CameraSensorSpec()
        camera_sensor_spec.uuid = "color_sensor"
        camera_sensor_spec.sensor_type = habitat_sim.SensorType.COLOR
        camera_sensor_spec.resolution = [self.height, self.width]
        camera_sensor_spec.position = [0.0, self.sensor_height, 0.0]
        camera_sensor_spec.hfov = self.hfov

        agent_cfg = habitat_sim.agent.AgentConfiguration()
        agent_cfg.sensor_specifications = [camera_sensor_spec]

        cfg = habitat_sim.Configuration(backend_cfg, [agent_cfg])
        self._sim = habitat_sim.Simulator(cfg)

    def reset(self) -> SimObservation:
        self.pose = SimAgentPose(z=self.sensor_height)
        self._step_counter = 0
        obs = self._sim.reset()
        rgb = obs["color_sensor"][:, :, :3]
        return SimObservation(
            rgb=rgb,
            timestamp_sec=time.time(),
            step_index=0,
        )

    def step(self, linear_velocity: float, angular_velocity: float, dt: float) -> SimObservation:
        self.pose = integrate_differential_drive(self.pose, linear_velocity, angular_velocity, dt)
        self._step_counter += 1

        # Move agent in Habitat
        agent = self._sim.get_agent(0)
        state = agent.get_state()
        state.position = np.array([self.pose.x, self.pose.z, self.pose.y])
        # Convert yaw to quaternion
        half_yaw = self.pose.yaw / 2.0
        state.rotation = np.quaternion(np.cos(half_yaw), 0, np.sin(half_yaw), 0)
        agent.set_state(state)

        obs = self._sim.get_sensor_observations()
        rgb = obs["color_sensor"][:, :, :3]
        return SimObservation(
            rgb=rgb,
            timestamp_sec=time.time(),
            step_index=self._step_counter,
        )

    def close(self) -> None:
        if self._sim is not None:
            self._sim.close()
            self._sim = None
