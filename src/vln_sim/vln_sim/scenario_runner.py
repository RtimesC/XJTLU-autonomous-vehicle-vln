"""Batch scenario runner for VLN simulation experiments."""

from dataclasses import dataclass
from typing import Any, Callable, List, Optional

try:
    from vln_core.action_adapter import ActionAdapter
    from vln_core.episode_manager import EpisodeManager, EpisodeManagerConfig
    from vln_core.safety_filter import SafetyFilter, SafetyFilterConfig
    from vln_core.episode_scenario import EpisodeScenario
    from vln_core.evaluator import EpisodeResult
except ImportError as e:
    raise ImportError(
        f"Failed to import vln_core dependencies. Ensure vln_core is in PYTHONPATH. Error: {e}"
    ) from e

try:
    from vln_sim.bridge_core import SimAgentPose
    from vln_sim.mock_scene_adapter import MockSceneAdapter
except ImportError as e:
    raise ImportError(f"Failed to import vln_sim dependencies. Error: {e}") from e


@dataclass
class ScenarioRunnerConfig:
    """Configuration for scenario runner."""
    sim_dt: float = 0.1
    image_width: int = 640
    image_height: int = 480
    safety_config: Optional[SafetyFilterConfig] = None
    verbose: bool = False


def run_episode(
    scenario: EpisodeScenario, policy: Any, config: ScenarioRunnerConfig
) -> EpisodeResult:
    """Runs a single episode in the closed-loop simulation.

    Args:
        scenario: Episode scenario definition.
        policy: Policy object with reset(episode_id, instruction) and predict(rgb, obs_stamp_sec).
        config: Runner configuration.

    Returns:
        EpisodeResult with recorded trajectory, velocities, latencies, and outcome.
    """
    sim = MockSceneAdapter(width=config.image_width, height=config.image_height)
    init_pose = SimAgentPose(x=scenario.start_x, y=scenario.start_y, yaw=scenario.start_yaw)
    obs = sim.reset(init_pose)

    episode_id = scenario.scenario_id

    policy.reset(episode_id=episode_id, instruction=scenario.instruction)

    adapter = ActionAdapter()
    adapter.reset_episode(episode_id=episode_id)

    safety_cfg = config.safety_config if config.safety_config is not None else SafetyFilterConfig()
    safety = SafetyFilter(config=safety_cfg)

    ep_cfg = EpisodeManagerConfig(
        max_duration_sec=scenario.max_duration_sec,
        max_steps=scenario.max_steps,
    )
    manager = EpisodeManager(config=ep_cfg)
    manager.start_episode(
        episode_id=episode_id,
        instruction=scenario.instruction,
        monotonic_now=0.0,
    )

    sim_time = 0.0
    trajectory: List[tuple] = []
    velocities: List[tuple] = []
    latencies: List[float] = []
    interventions = 0

    for _ in range(scenario.max_steps):
        # 1. Policy prediction
        act = policy.predict(obs.rgb, obs_stamp_sec=sim_time)

        # 2. ActionAdapter conversion
        twist, is_stop_triggered, _ = adapter.process_action(act)

        # 3. SafetyFilter constraints & acceleration limits
        safe_twist, status = safety.filter_command(
            twist,
            episode_id=act.episode_id,
            action_sequence_id=act.sequence_id,
            current_time_monotonic=sim_time,
        )

        # 4. EpisodeManager update
        finished, reason = manager.update_action(
            sequence_id=act.sequence_id,
            stop_probability=act.stop_probability,
            is_latched_stopped=adapter.is_stopped,
            monotonic_now=sim_time,
        )

        # 5. Record trajectory point
        trajectory.append((sim.pose.x, sim.pose.y))

        # 6. Record velocity command
        velocities.append((safe_twist.linear_x, safe_twist.angular_z))

        # 7. Record inference latency
        latencies.append(act.inference_latency_ms)

        # 8. Count safety interventions
        if status.command_modified:
            interventions += 1

        # 9. Break if finished
        if finished:
            break

        # 10. Integrate simulation step
        sim_time += config.sim_dt
        obs = sim.step(safe_twist.linear_x, safe_twist.angular_z, dt=config.sim_dt)

    record = manager.active_record
    completed = record.completed if record else False
    final_reason = (record.termination_reason if record else "unknown") or "unknown"
    total_steps = record.total_steps if record else len(trajectory)
    elapsed = record.elapsed_time_s if record else sim_time

    return EpisodeResult(
        scenario_id=scenario.scenario_id,
        episode_id=episode_id,
        completed=completed,
        termination_reason=final_reason,
        final_x=sim.pose.x,
        final_y=sim.pose.y,
        final_yaw=sim.pose.yaw,
        total_steps=total_steps,
        elapsed_time_sec=elapsed,
        trajectory=trajectory,
        collision_count=0,
        human_takeover_count=0,
        safety_intervention_count=interventions,
        inference_latencies_ms=latencies,
        velocity_commands=velocities,
        tags=list(scenario.tags),
    )


def run_batch(
    scenarios: List[EpisodeScenario],
    policy_factory: Callable[[], Any],
    config: ScenarioRunnerConfig,
) -> List[EpisodeResult]:
    """Runs a batch of simulation episodes.

    Args:
        scenarios: List of episode scenarios to execute.
        policy_factory: Callable that creates a fresh policy for each episode.
        config: Runner configuration.

    Returns:
        List of EpisodeResult, one per scenario.
    """
    results = []
    for i, scenario in enumerate(scenarios):
        if config.verbose:
            print(f"Running scenario {i + 1}/{len(scenarios)}: {scenario.scenario_id}")
        policy = policy_factory()
        res = run_episode(scenario, policy, config)
        results.append(res)
    return results
