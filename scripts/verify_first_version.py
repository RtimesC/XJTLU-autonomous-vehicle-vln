#!/usr/bin/env python3
"""Portable first-version verification; no camera, network, or external packages."""

from __future__ import annotations

import json
from pathlib import Path

from reasonnav_stage1.camera import CameraConfig, RGBDFrame, ReplayCamera, RealSenseD455fCamera
from reasonnav_stage1.contracts import Goal
from reasonnav_stage1.replay import JsonlReplay
from reasonnav_stage1.runtime import EpisodeRunner
from reasonnav_stage1.vlm import (
    MockObservationBackend,
    MockVLMBackend,
    TieredVLMBackend,
    VLMRequest,
    navigation_intent_from_json,
)


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    replay_path = ROOT / "examples" / "replay_episode.jsonl"
    responses = JsonlReplay(replay_path).run(
        goal=Goal(type="room", value="4205"),
        backend=MockVLMBackend(),
    )
    assert [response.intent.intent.value for response in responses] == ["advance", "observe"]

    tiered = TieredVLMBackend(observer=MockObservationBackend(), planner=MockVLMBackend())
    first_frame = next(JsonlReplay(replay_path).frames())
    tiered_response = tiered.generate(
        VLMRequest(
            goal=Goal(type="room", value="4205"),
            observation=first_frame.observation,
            memory=first_frame.memory,
            action_history=first_frame.action_history,
        )
    )
    assert tiered_response.metadata["routing"] == "tiered"

    runner = EpisodeRunner(
        goal=Goal(type="room", value="4205"),
        backend=MockVLMBackend(),
        frames=iter(JsonlReplay(replay_path).frames()),
    )
    runner.next_decision()
    runner.record_execution(status="completed", actual_result="到达下一个节点")
    assert runner.state.memory[0]["type"] == "execution_feedback"

    parsed = navigation_intent_from_json(json.dumps({
        "intent": "observe",
        "motion_owner": "camera",
        "target": "sign",
        "instruction": "观察标牌",
        "completion_condition": "读取文字",
        "stop": False,
        "confidence": 0.8,
    }))
    assert parsed.target == "sign"

    camera = ReplayCamera([RGBDFrame(rgb="rgb", depth="depth")])
    camera.start()
    assert camera.capture().rgb == "rgb"
    camera.stop()
    assert CameraConfig().expected_model == "D455f"
    assert RealSenseD455fCamera().config.expected_model == "D455f"
    print("first-version verification: OK")


if __name__ == "__main__":
    main()
