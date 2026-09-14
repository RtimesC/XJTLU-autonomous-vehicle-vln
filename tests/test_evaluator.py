"""Unit tests for VLN evaluator, scenario definition, and batch metrics."""

import os
import sys
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src/vln_core")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src/vln_sim")))

from vln_core.episode_scenario import (
    EpisodeScenario,
    SuccessRegion,
    load_scenarios_from_yaml,
    parse_scenarios,
)
from vln_core.evaluator import (
    AggregateMetrics,
    EpisodeMetrics,
    EpisodeResult,
    VlnEvaluator,
)


def test_success_region_contains():
    region = SuccessRegion(center_x=3.0, center_y=0.0, radius=0.5)
    assert region.contains(3.0, 0.0) is True
    assert region.contains(3.4, 0.0) is True
    assert region.contains(3.5, 0.0) is True  # on boundary
    assert region.contains(3.6, 0.0) is False  # outside
    assert region.contains(3.0, 0.6) is False


def test_evaluator_success_episode():
    scenario = EpisodeScenario(
        scenario_id="scen_01",
        instruction="Navigate forward 3 meters",
        start_x=0.0,
        start_y=0.0,
        start_yaw=0.0,
        success_region=SuccessRegion(center_x=3.0, center_y=0.0, radius=0.5),
    )

    result = EpisodeResult(
        scenario_id="scen_01",
        episode_id="ep_01",
        completed=True,
        termination_reason="policy_stop_latch",
        final_x=2.95,
        final_y=0.05,
        final_yaw=0.0,
        total_steps=60,
        elapsed_time_sec=6.0,
        trajectory=[(0.0, 0.0), (1.5, 0.0), (2.95, 0.05)],
        collision_count=0,
        human_takeover_count=0,
        safety_intervention_count=2,
        inference_latencies_ms=[10.0, 15.0, 20.0, 25.0],
        velocity_commands=[(0.0, 0.0), (0.35, 0.0), (0.35, 0.0), (0.0, 0.0)],
    )

    evaluator = VlnEvaluator()
    metrics = evaluator.evaluate_episode(result, scenario)

    assert metrics.success is True
    assert metrics.stop_distance_m < 0.5
    assert metrics.shortest_path_m == pytest.approx(3.0)
    assert metrics.path_length_m >= metrics.shortest_path_m * 0.95
    assert metrics.spl > 0.90
    assert metrics.collision_count == 0
    assert metrics.human_takeover_count == 0
    assert metrics.safety_intervention_count == 2
    assert metrics.inference_latency_p50_ms == 20.0
    assert metrics.inference_latency_p95_ms == 25.0
    assert metrics.velocity_jerk_mean > 0.0


def test_evaluator_failure_cases():
    scenario = EpisodeScenario(
        scenario_id="scen_fail",
        instruction="Navigate forward",
        start_x=0.0,
        start_y=0.0,
        start_yaw=0.0,
        success_region=SuccessRegion(center_x=3.0, center_y=0.0, radius=0.5),
    )

    evaluator = VlnEvaluator()

    # Case 1: Stopped too far away (distance failure)
    res_far = EpisodeResult(
        scenario_id="scen_fail",
        episode_id="ep_far",
        completed=True,
        termination_reason="policy_stop_latch",
        final_x=1.5,  # 1.5m away from 3.0m (radius is 0.5m)
        final_y=0.0,
        final_yaw=0.0,
        total_steps=40,
        elapsed_time_sec=4.0,
        trajectory=[(0.0, 0.0), (1.5, 0.0)],
    )
    m_far = evaluator.evaluate_episode(res_far, scenario)
    assert m_far.success is False
    assert m_far.spl == 0.0

    # Case 2: Reached region but collided (collision failure)
    res_coll = EpisodeResult(
        scenario_id="scen_fail",
        episode_id="ep_coll",
        completed=True,
        termination_reason="policy_stop_latch",
        final_x=3.0,
        final_y=0.0,
        final_yaw=0.0,
        total_steps=50,
        elapsed_time_sec=5.0,
        trajectory=[(0.0, 0.0), (3.0, 0.0)],
        collision_count=1,
    )
    m_coll = evaluator.evaluate_episode(res_coll, scenario)
    assert m_coll.success is False
    assert m_coll.spl == 0.0

    # Case 3: Reached region but human took over
    res_to = EpisodeResult(
        scenario_id="scen_fail",
        episode_id="ep_to",
        completed=True,
        termination_reason="policy_stop_latch",
        final_x=3.0,
        final_y=0.0,
        final_yaw=0.0,
        total_steps=50,
        elapsed_time_sec=5.0,
        trajectory=[(0.0, 0.0), (3.0, 0.0)],
        human_takeover_count=1,
    )
    m_to = evaluator.evaluate_episode(res_to, scenario)
    assert m_to.success is False
    assert m_to.spl == 0.0


def test_evaluator_batch_aggregation():
    scenario = EpisodeScenario(
        scenario_id="scen_batch",
        instruction="Go to door",
        start_x=0.0,
        start_y=0.0,
        start_yaw=0.0,
        success_region=SuccessRegion(center_x=3.0, center_y=0.0, radius=0.5),
    )

    evaluator = VlnEvaluator()

    # Empty batch
    _, agg_empty = evaluator.evaluate_batch([])
    assert agg_empty.total_episodes == 0
    assert agg_empty.success_rate == 0.0

    # 1 success + 1 failure
    res_succ = EpisodeResult(
        scenario_id="scen_batch",
        episode_id="ep_s",
        completed=True,
        termination_reason="policy_stop_latch",
        final_x=3.0,
        final_y=0.0,
        final_yaw=0.0,
        total_steps=30,
        elapsed_time_sec=3.0,
        trajectory=[(0.0, 0.0), (3.0, 0.0)],
        safety_intervention_count=1,
    )
    res_fail = EpisodeResult(
        scenario_id="scen_batch",
        episode_id="ep_f",
        completed=False,
        termination_reason="max_duration_timeout",
        final_x=1.0,
        final_y=0.0,
        final_yaw=0.0,
        total_steps=50,
        elapsed_time_sec=5.0,
        trajectory=[(0.0, 0.0), (1.0, 0.0)],
        safety_intervention_count=2,
    )

    ep_list, agg = evaluator.evaluate_batch([(res_succ, scenario), (res_fail, scenario)])
    assert len(ep_list) == 2
    assert agg.total_episodes == 2
    assert agg.success_rate == 0.5
    assert agg.total_safety_interventions == 3
    assert agg.mean_spl > 0.0


def test_load_scenarios_from_baseline_yaml():
    yaml_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "../src/vln_sim/scenarios/doornav_baseline.yaml")
    )
    scenarios = load_scenarios_from_yaml(yaml_path)
    assert len(scenarios) == 7
    ids = [s.scenario_id for s in scenarios]
    assert "straight_approach" in ids
    assert "heading_offset_15deg" in ids
    assert "impossible_timeout" in ids
