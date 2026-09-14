"""End-to-end closed-loop simulation tests for ReactiveDoorNavPolicy on Mac.

Pipeline:
  MockSceneAdapter (synthetic corridor + doorway)
    -> ReactiveDoorNavPolicy (grounder + tracker + state machine)
    -> ActionAdapter (protocol conversion + stop latching)
    -> SafetyFilter (velocity limits + acceleration slew rate)
    -> EpisodeManager (NavigateLanguage lifecycle governance)
    -> MockSceneAdapter (differential drive kinematics integration)
"""

import os
import sys
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src/vln_core")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src/vln_policy")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src/vln_sim")))

from vln_core.action_adapter import ActionAdapter
from vln_core.episode_manager import EpisodeManager, EpisodeManagerConfig, EpisodeState
from vln_core.safety_filter import SafetyFilter, SafetyFilterConfig
from vln_policy.door_nav_policy import DoorNavState, ReactiveDoorNavPolicy
from vln_sim.bridge_core import SimAgentPose
from vln_sim.mock_scene_adapter import MockSceneAdapter


def test_doornav_closed_loop_success():
    """Verifies that DoorNav policy successfully discovers doorway, approaches, verifies, and latches stop."""
    sim = MockSceneAdapter(width=640, height=480)
    # Start with a slight heading offset (0.15 rad ~ 8.6 degrees left)
    obs = sim.reset(SimAgentPose(x=0.0, y=0.0, yaw=0.15))

    policy = ReactiveDoorNavPolicy()
    policy.reset(episode_id="ep_closed_loop_001", instruction="approach doorway and stop")

    adapter = ActionAdapter()
    adapter.reset_episode(episode_id="ep_closed_loop_001")

    safety_cfg = SafetyFilterConfig(
        max_linear_velocity=0.8,
        max_angular_velocity=1.0,
        max_linear_accel=1.5,
        max_angular_accel=1.5,
    )
    safety = SafetyFilter(config=safety_cfg)

    ep_cfg = EpisodeManagerConfig(max_duration_sec=30.0, max_steps=200)
    manager = EpisodeManager(config=ep_cfg)
    ok, _ = manager.start_episode(
        episode_id="ep_closed_loop_001",
        instruction="approach doorway and stop",
        monotonic_now=0.0,
    )
    assert ok

    sim_time = 0.0
    dt = 0.1
    max_test_steps = 120
    reached_goal = False

    states_visited = set()

    for step in range(1, max_test_steps + 1):
        # 1. Policy prediction
        act = policy.predict(obs.rgb, obs_stamp_sec=sim_time)
        states_visited.add(policy.state)

        # 2. ActionAdapter conversion
        twist, is_stop_triggered, _ = adapter.process_action(act)

        # 3. SafetyFilter constraints & acceleration limits
        safe_twist, status = safety.filter_command(
            twist,
            episode_id=act.episode_id,
            action_sequence_id=act.sequence_id,
            current_time_monotonic=sim_time,
        )

        # Invariance check: velocities within strict vehicle bounds
        assert -0.2 <= safe_twist.linear_x <= 0.8
        assert -1.0 <= safe_twist.angular_z <= 1.0

        # 4. EpisodeManager update
        finished, reason = manager.update_action(
            sequence_id=act.sequence_id,
            stop_probability=act.stop_probability,
            is_latched_stopped=adapter.is_stopped,
            monotonic_now=sim_time,
        )

        if finished:
            reached_goal = True
            break

        # 5. Integrate simulation step
        sim_time += dt
        obs = sim.step(safe_twist.linear_x, safe_twist.angular_z, dt=dt)

    assert reached_goal is True, f"Policy failed to reach goal within {max_test_steps} steps."
    assert manager.active_record.state == EpisodeState.COMPLETED
    assert manager.active_record.completed is True
    assert manager.active_record.termination_reason == "policy_stop_latch"

    # Verify state progression went through approach and verify before stop
    assert DoorNavState.APPROACH in states_visited
    assert DoorNavState.VERIFY in states_visited
    assert DoorNavState.STOP in states_visited

    # Verify vehicle arrived near the doorway (x ~ 2.9m) and has zero velocity
    assert sim.pose.x >= 2.5
    assert safe_twist.linear_x == pytest.approx(0.0, abs=1e-3)
    assert safe_twist.angular_z == pytest.approx(0.0, abs=1e-3)


def test_doornav_closed_loop_cancellation():
    """Verifies that an in-flight simulation episode can be safely cancelled by operator."""
    sim = MockSceneAdapter()
    obs = sim.reset()

    policy = ReactiveDoorNavPolicy()
    policy.reset("ep_cancel_test")

    adapter = ActionAdapter()
    adapter.reset_episode("ep_cancel_test")

    safety = SafetyFilter()
    manager = EpisodeManager()
    manager.start_episode("ep_cancel_test", "abort halfway", monotonic_now=0.0)

    # Step for 5 cycles
    sim_time = 0.0
    for _ in range(5):
        act = policy.predict(obs.rgb, obs_stamp_sec=sim_time)
        twist, _, _ = adapter.process_action(act)
        safe_twist, _ = safety.filter_command(
            twist,
            episode_id=act.episode_id,
            action_sequence_id=act.sequence_id,
            current_time_monotonic=sim_time,
        )
        manager.update_action(act.sequence_id, act.stop_probability, adapter.is_stopped, monotonic_now=sim_time)
        sim_time += 0.1
        obs = sim.step(safe_twist.linear_x, safe_twist.angular_z, dt=0.1)

    assert manager.is_running is True

    # Operator cancels
    ok, msg = manager.cancel_episode("operator_e_stop", monotonic_now=sim_time)
    assert ok
    assert not manager.is_running
    assert manager.active_record.state == EpisodeState.CANCELLED
    assert manager.active_record.completed is False


def test_doornav_closed_loop_timeout_guard():
    """Verifies that EpisodeManager terminates with timeout if goal is not reached in max_duration_sec."""
    sim = MockSceneAdapter()
    obs = sim.reset()

    policy = ReactiveDoorNavPolicy()
    policy.reset("ep_timeout_test")

    adapter = ActionAdapter()
    adapter.reset_episode("ep_timeout_test")

    safety = SafetyFilter()
    ep_cfg = EpisodeManagerConfig(max_duration_sec=1.0, max_steps=100)
    manager = EpisodeManager(config=ep_cfg)
    manager.start_episode("ep_timeout_test", "timeout test", monotonic_now=0.0)

    sim_time = 0.0
    finished = False
    reason = ""

    for _ in range(25):
        act = policy.predict(obs.rgb, obs_stamp_sec=sim_time)
        twist, _, _ = adapter.process_action(act)
        safe_twist, _ = safety.filter_command(
            twist,
            episode_id=act.episode_id,
            action_sequence_id=act.sequence_id,
            current_time_monotonic=sim_time,
        )
        finished, reason = manager.update_action(
            act.sequence_id,
            act.stop_probability,
            adapter.is_stopped,
            monotonic_now=sim_time,
        )
        if finished:
            break
        sim_time += 0.1
        obs = sim.step(safe_twist.linear_x, safe_twist.angular_z, dt=0.1)

    assert finished is True
    assert reason == "max_duration_timeout"
    assert manager.active_record.state == EpisodeState.FAILED
