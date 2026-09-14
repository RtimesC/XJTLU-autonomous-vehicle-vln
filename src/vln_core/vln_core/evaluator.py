"""VLN experiment evaluator computing per-episode and aggregate metrics."""

import math
from dataclasses import dataclass, field
from typing import List, Tuple, Optional

from .episode_scenario import EpisodeScenario, SuccessRegion


@dataclass
class EpisodeResult:
    scenario_id: str
    episode_id: str
    completed: bool
    termination_reason: str
    final_x: float
    final_y: float
    final_yaw: float
    total_steps: int
    elapsed_time_sec: float
    trajectory: List[Tuple[float, float]]
    collision_count: int = 0
    human_takeover_count: int = 0
    safety_intervention_count: int = 0
    inference_latencies_ms: List[float] = field(default_factory=list)
    velocity_commands: List[Tuple[float, float]] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)


@dataclass
class EpisodeMetrics:
    scenario_id: str
    episode_id: str
    success: bool
    spl: float
    stop_distance_m: float
    path_length_m: float
    shortest_path_m: float
    collision_count: int
    human_takeover_count: int
    safety_intervention_count: int
    inference_latency_p50_ms: float
    inference_latency_p95_ms: float
    velocity_jerk_mean: float
    angular_jerk_mean: float
    elapsed_time_sec: float


@dataclass
class AggregateMetrics:
    total_episodes: int
    success_rate: float
    mean_spl: float
    mean_stop_distance_m: float
    mean_path_length_m: float
    mean_inference_latency_p95_ms: float
    total_collisions: int
    total_human_takeovers: int
    total_safety_interventions: int


class VlnEvaluator:
    def __init__(self) -> None:
        pass

    def evaluate_episode(self, result: EpisodeResult, scenario: EpisodeScenario) -> EpisodeMetrics:
        # Distance metrics
        stop_dx = result.final_x - scenario.success_region.center_x
        stop_dy = result.final_y - scenario.success_region.center_y
        stop_distance_m = math.sqrt(stop_dx * stop_dx + stop_dy * stop_dy)
        
        start_dx = scenario.start_x - scenario.success_region.center_x
        start_dy = scenario.start_y - scenario.success_region.center_y
        shortest_path_m = math.sqrt(start_dx * start_dx + start_dy * start_dy)

        # Path length
        path_length_m = 0.0
        if result.trajectory and len(result.trajectory) > 1:
            for i in range(1, len(result.trajectory)):
                p1 = result.trajectory[i-1]
                p2 = result.trajectory[i]
                dx = p2[0] - p1[0]
                dy = p2[1] - p1[1]
                path_length_m += math.sqrt(dx * dx + dy * dy)
        
        # Success and SPL
        in_region = stop_distance_m <= scenario.success_region.radius
        success = bool(result.completed and in_region and result.collision_count == 0 and result.human_takeover_count == 0)
        
        spl = 0.0
        if success:
            max_dist = max(path_length_m, shortest_path_m)
            if max_dist > 0.0:
                spl = shortest_path_m / max_dist
            else:
                spl = 1.0
                
        # Latency percentiles
        p50 = 0.0
        p95 = 0.0
        if result.inference_latencies_ms:
            sorted_latencies = sorted(result.inference_latencies_ms)
            n = len(sorted_latencies)
            p50 = sorted_latencies[int(n * 0.50)]
            p95 = sorted_latencies[int(n * 0.95)]
            
        # Velocity jerk
        velocity_jerk_mean = 0.0
        angular_jerk_mean = 0.0
        if result.velocity_commands and len(result.velocity_commands) > 1:
            vel_diff_sum = 0.0
            ang_diff_sum = 0.0
            for i in range(1, len(result.velocity_commands)):
                v1, w1 = result.velocity_commands[i-1]
                v2, w2 = result.velocity_commands[i]
                vel_diff_sum += abs(v2 - v1)
                ang_diff_sum += abs(w2 - w1)
            n_diffs = len(result.velocity_commands) - 1
            if n_diffs > 0:
                velocity_jerk_mean = vel_diff_sum / n_diffs
                angular_jerk_mean = ang_diff_sum / n_diffs

        return EpisodeMetrics(
            scenario_id=result.scenario_id,
            episode_id=result.episode_id,
            success=success,
            spl=spl,
            stop_distance_m=stop_distance_m,
            path_length_m=path_length_m,
            shortest_path_m=shortest_path_m,
            collision_count=result.collision_count,
            human_takeover_count=result.human_takeover_count,
            safety_intervention_count=result.safety_intervention_count,
            inference_latency_p50_ms=p50,
            inference_latency_p95_ms=p95,
            velocity_jerk_mean=velocity_jerk_mean,
            angular_jerk_mean=angular_jerk_mean,
            elapsed_time_sec=result.elapsed_time_sec
        )

    def evaluate_batch(self, results: List[Tuple[EpisodeResult, EpisodeScenario]]) -> Tuple[List[EpisodeMetrics], AggregateMetrics]:
        ep_metrics = []
        for res, scen in results:
            ep_metrics.append(self.evaluate_episode(res, scen))
            
        total_ep = len(ep_metrics)
        if total_ep == 0:
            agg = AggregateMetrics(
                total_episodes=0,
                success_rate=0.0,
                mean_spl=0.0,
                mean_stop_distance_m=0.0,
                mean_path_length_m=0.0,
                mean_inference_latency_p95_ms=0.0,
                total_collisions=0,
                total_human_takeovers=0,
                total_safety_interventions=0
            )
            return [], agg
            
        successes = sum(1 for m in ep_metrics if m.success)
        success_rate = successes / total_ep
        mean_spl = sum(m.spl for m in ep_metrics) / total_ep
        mean_stop_dist = sum(m.stop_distance_m for m in ep_metrics) / total_ep
        mean_path_len = sum(m.path_length_m for m in ep_metrics) / total_ep
        mean_p95 = sum(m.inference_latency_p95_ms for m in ep_metrics) / total_ep
        
        total_coll = sum(m.collision_count for m in ep_metrics)
        total_to = sum(m.human_takeover_count for m in ep_metrics)
        total_si = sum(m.safety_intervention_count for m in ep_metrics)
        
        agg = AggregateMetrics(
            total_episodes=total_ep,
            success_rate=success_rate,
            mean_spl=mean_spl,
            mean_stop_distance_m=mean_stop_dist,
            mean_path_length_m=mean_path_len,
            mean_inference_latency_p95_ms=mean_p95,
            total_collisions=total_coll,
            total_human_takeovers=total_to,
            total_safety_interventions=total_si
        )
        return ep_metrics, agg
