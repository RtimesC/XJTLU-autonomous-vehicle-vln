#!/usr/bin/env python3
"""Run closed-loop simulation of DoorNav policy on Mac (or headless CI).

Demonstrates the entire end-to-end perception -> policy -> safety -> kinematics pipeline:
1. MockSceneAdapter generates procedural RGB corridor frames with a doorway ahead.
2. ReactiveDoorNavPolicy detects doorway contours, tracks candidate with IoU, centers heading, and approaches.
3. ActionAdapter converts policy action to Twist stamped format and tracks consecutive stop predictions.
4. SafetyFilter enforces vehicle velocity bounds and acceleration slew rates.
5. EpisodeManager governs episode lifecycle, timeout, and latch-driven completion.
6. Differential drive kinematics integrates safe velocities into updated vehicle pose.
"""

import math
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src/vln_core")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src/vln_policy")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src/vln_sim")))

from vln_core.action_adapter import ActionAdapter
from vln_core.episode_manager import EpisodeManager, EpisodeManagerConfig, EpisodeState
from vln_core.safety_filter import SafetyFilter, SafetyFilterConfig
from vln_policy.door_nav_policy import DoorNavState, ReactiveDoorNavPolicy
from vln_sim.bridge_core import SimAgentPose
from vln_sim.mock_scene_adapter import MockSceneAdapter


def run_simulation(
    episode_id: str = "doornav_mac_demo_01",
    instruction: str = "Navigate along the corridor and stop at the open doorway",
    init_yaw_rad: float = 0.20,
    dt: float = 0.1,
    max_steps: int = 150,
):
    print("=" * 95)
    print("         XJTLU Autonomous Vehicle VLN - Closed-Loop Simulation (Mac / CI)")
    print("=" * 95)
    print(f" Episode ID   : {episode_id}")
    print(f" Instruction  : \"{instruction}\"")
    print(f" Initial Pose : x=0.00m, y=0.00m, yaw={init_yaw_rad:+.2f} rad ({math.degrees(init_yaw_rad):+.1f}°)")
    print(f" Timestep dt  : {dt}s")
    print("-" * 95)
    print(f"{'Step':>5} | {'Sim Time':>8} | {'State':^8} | {'Pose (x, y, yaw)':^23} | {'Raw (v, w)':^16} | {'Safe (v, w)':^16} | {'p_stop':>6}")
    print("-" * 95)

    sim = MockSceneAdapter(width=640, height=480)
    obs = sim.reset(SimAgentPose(x=0.0, y=0.0, yaw=init_yaw_rad))

    policy = ReactiveDoorNavPolicy()
    policy.reset(episode_id=episode_id, instruction=instruction)

    adapter = ActionAdapter()
    adapter.reset_episode(episode_id=episode_id)

    safety = SafetyFilter(
        SafetyFilterConfig(
            max_linear_velocity=0.6,
            max_angular_velocity=0.8,
            max_linear_accel=1.5,
            max_angular_accel=1.5,
        )
    )

    manager = EpisodeManager(EpisodeManagerConfig(max_duration_sec=30.0, max_steps=max_steps))
    manager.start_episode(episode_id=episode_id, instruction=instruction, monotonic_now=0.0)

    sim_time = 0.0
    completed = False

    for step in range(1, max_steps + 1):
        # 1. Perception & Policy prediction
        act = policy.predict(obs.rgb, obs_stamp_sec=sim_time)

        # 2. Action Adaptation
        twist, is_stop_triggered, _ = adapter.process_action(act)

        # 3. Safety Filtering
        safe_twist, safety_status = safety.filter_command(
            twist,
            episode_id=act.episode_id,
            action_sequence_id=act.sequence_id,
            current_time_monotonic=sim_time,
        )

        # 4. Episode Manager Governance
        finished, reason = manager.update_action(
            sequence_id=act.sequence_id,
            stop_probability=act.stop_probability,
            is_latched_stopped=adapter.is_stopped,
            monotonic_now=sim_time,
        )

        # Formatting telemetry
        pose_str = f"({sim.pose.x:.2f}m, {sim.pose.y:.2f}m, {sim.pose.yaw:+.2f}r)"
        raw_cmd_str = f"({act.linear_velocity:.2f}, {act.angular_velocity:+.2f})"
        safe_cmd_str = f"({safe_twist.linear_x:.2f}, {safe_twist.angular_z:+.2f})"

        # Print telemetry
        if step <= 5 or step % 5 == 0 or finished or policy.state in (DoorNavState.VERIFY, DoorNavState.STOP):
            print(
                f"{step:5d} | {sim_time:7.2f}s | {policy.state.value:^8} | "
                f"{pose_str:^23} | {raw_cmd_str:^16} | {safe_cmd_str:^16} | {act.stop_probability:6.2f}"
            )

        if finished:
            completed = True
            print("-" * 95)
            print(">>> EPISODE FINISHED SUCCESSFULLY <<<")
            print(f"  Final State         : {manager.active_record.state.value}")
            print(f"  Termination Reason  : {reason}")
            print(f"  Total Steps         : {step}")
            print(f"  Simulated Duration  : {sim_time:.2f}s")
            print(f"  Final Pose          : x={sim.pose.x:.3f}m, y={sim.pose.y:.3f}m, yaw={sim.pose.yaw:+.3f} rad")
            print(f"  Final Velocity      : v={safe_twist.linear_x:.3f} m/s, w={safe_twist.angular_z:.3f} rad/s")
            print(f"  Stop Latch Confirmed: {adapter.is_stopped}")
            print("=" * 95)
            break

        # 5. Kinematics integration in simulation
        sim_time += dt
        obs = sim.step(safe_twist.linear_x, safe_twist.angular_z, dt=dt)

    if not completed:
        print("\nSimulation reached max step limit without latching stop.")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(run_simulation())
