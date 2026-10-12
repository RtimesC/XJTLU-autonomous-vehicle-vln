"""One-step episode orchestration and portable run persistence."""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .contracts import EpisodeState, ExecutionResult, Goal, PlatformMode, StepRecord
from .replay import ReplayFrame
from .vlm import VLMBackend, VLMRequest, VLMResponse


class EpisodeStore:
    """Persist an episode as human-readable JSON without external dependencies."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, state: EpisodeState) -> Path:
        destination = self.root / f"{state.episode_id}.json"
        temporary = destination.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(state.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(destination)
        return destination


class EpisodeRunner:
    """Coordinate observation, one VLM decision, execution feedback, and memory."""

    def __init__(
        self,
        *,
        goal: Goal,
        backend: VLMBackend,
        frames: Iterator[ReplayFrame],
        platform_mode: PlatformMode = PlatformMode.HUMAN_CARRIED,
        store: EpisodeStore | None = None,
        episode_id: str | None = None,
    ) -> None:
        self.goal = goal
        self.backend = backend
        self.frames = frames
        self.platform_mode = platform_mode
        self.store = store
        self.state = EpisodeState(
            episode_id=episode_id or _episode_id(goal),
            goal=goal,
            platform_mode=platform_mode,
        )

    def next_decision(self) -> VLMResponse:
        if self.state.status == "stopped":
            raise RuntimeError("episode is stopped")
        if self.state.records and self.state.records[-1].execution is None:
            raise RuntimeError("execute the pending intent before requesting another decision")
        try:
            frame = next(self.frames)
        except StopIteration as exc:
            self.state.status = "no_more_observations"
            self._save()
            raise RuntimeError("replay has no more observations") from exc

        request = VLMRequest(
            goal=self.goal,
            observation=frame.observation,
            memory=self.state.memory,
            action_history=[
                {
                    "step_id": record.observation.step_id,
                    "intent": record.intent.intent.value,
                    "execution": record.execution.status if record.execution else None,
                }
                for record in self.state.records
            ],
        )
        response = self.backend.generate(request)
        self.state.current_step = frame.observation.step_id
        self.state.status = "awaiting_execution"
        self.state.records.append(
            StepRecord(observation=frame.observation, intent=response.intent)
        )
        self._save()
        return response

    def record_execution(
        self,
        *,
        status: str,
        actual_result: str,
        operator_note: str = "",
    ) -> ExecutionResult:
        if not self.state.records or self.state.records[-1].execution is not None:
            raise RuntimeError("there is no pending intent to execute")
        if status not in {"completed", "failed", "skipped"}:
            raise ValueError("status must be completed, failed, or skipped")

        result = ExecutionResult(
            status=status,
            actual_result=actual_result,
            operator_note=operator_note,
        )
        record = self.state.records[-1]
        record.execution = result
        if actual_result.strip() or operator_note.strip():
            update = {
                "source_step": record.observation.step_id,
                "type": "execution_feedback",
                "status": status,
                "text": actual_result.strip(),
                "operator_note": operator_note.strip(),
            }
            record.memory_updates.append(update)
            self.state.memory.append(update)
        self.state.status = "stopped" if record.intent.stop else "searching"
        self._save()
        return result

    def snapshot(self) -> dict[str, Any]:
        return self.state.to_dict()

    def _save(self) -> None:
        if self.store is not None:
            self.store.save(self.state)


def _episode_id(goal: Goal) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_goal = re.sub(r"[^A-Za-z0-9_-]+", "_", goal.value).strip("_") or "goal"
    return f"episode-{safe_goal}-{timestamp}"
