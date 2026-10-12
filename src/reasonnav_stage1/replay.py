"""Offline episode replay helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from .contracts import DepthSummary, Goal, Observation, PlatformMode
from .vlm import VLMBackend, VLMRequest, VLMResponse


@dataclass(slots=True)
class ReplayFrame:
    observation: Observation
    memory: list[dict[str, Any]]
    action_history: list[dict[str, Any]]


class JsonlReplay:
    """Read portable replay frames from one JSONL file."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def frames(self) -> Iterator[ReplayFrame]:
        with self.path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip() or line.lstrip().startswith("#"):
                    continue
                try:
                    payload = json.loads(line)
                    yield _frame_from_dict(payload)
                except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                    raise ValueError(f"invalid replay frame at line {line_number}") from exc

    def run(
        self,
        *,
        goal: Goal,
        backend: VLMBackend,
        platform_mode: PlatformMode = PlatformMode.HUMAN_CARRIED,
    ) -> list[VLMResponse]:
        responses: list[VLMResponse] = []
        for frame in self.frames():
            request = VLMRequest(
                goal=goal,
                observation=frame.observation,
                memory=frame.memory,
                action_history=frame.action_history,
            )
            responses.append(backend.generate(request))
        return responses


def _frame_from_dict(payload: dict[str, Any]) -> ReplayFrame:
    depth = payload.get("depth_summary", {})
    observation = Observation(
        step_id=int(payload["step_id"]),
        rgb_path=payload.get("rgb_path"),
        depth_path=payload.get("depth_path"),
        depth_summary=DepthSummary(
            front_distance_m=depth.get("front_distance_m"),
            left_distance_m=depth.get("left_distance_m"),
            right_distance_m=depth.get("right_distance_m"),
            target_distance_m=depth.get("target_distance_m"),
            valid_fraction=depth.get("valid_fraction"),
        ),
        platform_mode=PlatformMode(payload.get("platform_mode", "human_carried")),
        metadata=payload.get("metadata", {}),
    )
    return ReplayFrame(
        observation=observation,
        memory=payload.get("memory", []),
        action_history=payload.get("action_history", []),
    )
