"""VLM contracts and a provider-neutral OpenAI-compatible client."""

from __future__ import annotations

import base64
import json
import mimetypes
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from dataclasses import replace
from pathlib import Path
from typing import Any, Protocol

from .contracts import (
    Goal,
    IntentType,
    MotionOwner,
    NavigationIntent,
    Observation,
    PlatformMode,
)


@dataclass(slots=True)
class VLMRequest:
    goal: Goal
    observation: Observation
    memory: list[dict[str, Any]] = field(default_factory=list)
    action_history: list[dict[str, Any]] = field(default_factory=list)
    system_instruction: str = (
        "You are a high-level indoor navigation planner. "
        "Return exactly one JSON navigation intent. Do not output velocity, "
        "coordinates, or a multi-step plan."
    )

    def to_text(self) -> str:
        payload = {
            "goal": {"type": self.goal.type, "value": self.goal.value},
            "observation": {
                "step_id": self.observation.step_id,
                "platform_mode": self.observation.platform_mode.value,
                "depth_summary": {
                    "front_distance_m": self.observation.depth_summary.front_distance_m,
                    "left_distance_m": self.observation.depth_summary.left_distance_m,
                    "right_distance_m": self.observation.depth_summary.right_distance_m,
                    "target_distance_m": self.observation.depth_summary.target_distance_m,
                    "valid_fraction": self.observation.depth_summary.valid_fraction,
                },
                "metadata": self.observation.metadata,
            },
            "memory": self.memory,
            "action_history": self.action_history,
            "output_schema": {
                "intent": "observe | advance | inspect | stop",
                "motion_owner": "none | camera | body | mobile_base | gimbal",
                "target": "string or null",
                "instruction": "one executable instruction",
                "completion_condition": "how the step ends",
                "direction": "optional relative direction",
                "distance_hint": "optional qualitative distance",
                "speed_level": "optional qualitative speed",
                "stop": "boolean",
                "reason": "short explanation",
                "confidence": "number from 0 to 1"
            },
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)


@dataclass(slots=True)
class VLMResponse:
    intent: NavigationIntent
    raw_text: str
    latency_ms: float
    provider: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ObservationSummary:
    """Compact low-cost observation result passed to the planner."""

    scene: str
    landmarks: list[dict[str, Any]] = field(default_factory=list)
    uncertainty: float | None = None
    raw_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "scene": self.scene,
            "landmarks": self.landmarks,
            "uncertainty": self.uncertainty,
        }


class VLMBackend(Protocol):
    def generate(self, request: VLMRequest) -> VLMResponse:
        ...


class ObservationBackend(Protocol):
    def summarize(self, request: VLMRequest) -> ObservationSummary:
        ...


class MockVLMBackend:
    """Deterministic backend for macOS replay and contract validation."""

    def generate(self, request: VLMRequest) -> VLMResponse:
        started = time.perf_counter()
        if request.observation.step_id == 0:
            intent = NavigationIntent(
                intent=IntentType.ADVANCE,
                motion_owner=MotionOwner.BODY,
                target="next_corridor_node",
                instruction="沿当前走廊缓慢向前移动一小段",
                completion_condition="看到下一个走廊节点或新的方向信息",
                distance_hint="short",
                speed_level="slow",
                reason="开始探索当前走廊",
                confidence=0.5,
            )
        else:
            intent = NavigationIntent(
                intent=IntentType.OBSERVE,
                motion_owner=MotionOwner.CAMERA,
                target="visible_sign_or_room_label",
                instruction="原地转动相机，观察当前可见的标牌或门牌",
                completion_condition="读取到清晰文字或确认当前没有可读标识",
                direction="scan",
                reason="先获得语义地标，再决定身体移动方向",
                confidence=0.5,
            )
        errors = intent.validate()
        if errors:
            raise ValueError(f"mock intent is invalid: {errors}")
        return VLMResponse(
            intent=intent,
            raw_text=json.dumps(_intent_dict(intent), ensure_ascii=False),
            latency_ms=(time.perf_counter() - started) * 1000,
            provider="mock",
        )


class MockObservationBackend:
    """Deterministic observation stage for offline replay and verification."""

    def summarize(self, request: VLMRequest) -> ObservationSummary:
        depth = request.observation.depth_summary
        scene = "前方走廊，深度有效" if depth.valid_fraction else "当前观测场景"
        return ObservationSummary(
            scene=scene,
            landmarks=list(request.memory),
            uncertainty=0.2 if depth.valid_fraction else 0.8,
            raw_text=json.dumps({"scene": scene, "landmarks": list(request.memory)}, ensure_ascii=False),
        )


class TieredVLMBackend:
    """Use a cheap observer before the higher-quality navigation planner."""

    def __init__(self, *, observer: ObservationBackend, planner: VLMBackend) -> None:
        self.observer = observer
        self.planner = planner

    def generate(self, request: VLMRequest) -> VLMResponse:
        summary = self.observer.summarize(request)
        metadata = dict(request.observation.metadata)
        metadata["observation_summary"] = summary.to_dict()
        enriched_observation = replace(request.observation, metadata=metadata)
        enriched_request = replace(request, observation=enriched_observation)
        response = self.planner.generate(enriched_request)
        response.metadata.update(
            {
                "routing": "tiered",
                "observation_model": getattr(self.observer, "model", "mock"),
                "planner_model": getattr(self.planner, "model", "mock"),
                "observation_summary": summary.to_dict(),
            }
        )
        return response


class OpenAICompatibleVLM:
    """Minimal standard-library client for an OpenAI-compatible chat endpoint.

    It is intentionally provider-neutral. The caller supplies the endpoint,
    model, and API key through configuration; this class never reads a key
    from source files.
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_s: float = 60.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_s = timeout_s

    def generate(self, request: VLMRequest) -> VLMResponse:
        started = time.perf_counter()
        content: list[dict[str, Any]] = [{"type": "text", "text": request.to_text()}]
        if request.observation.rgb_path:
            image_url = _image_as_data_url(Path(request.observation.rgb_path))
            if image_url:
                content.append({"type": "image_url", "image_url": {"url": image_url}})

        body = {
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": request.system_instruction},
                {"role": "user", "content": content},
            ],
        }
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        http_request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=data,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(http_request, timeout=self.timeout_s) as response:
                response_data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"VLM HTTP {exc.code}: {detail[:500]}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"VLM connection failed: {exc.reason}") from exc

        raw_text = _extract_chat_content(response_data)
        intent = navigation_intent_from_json(raw_text)
        return VLMResponse(
            intent=intent,
            raw_text=raw_text,
            latency_ms=(time.perf_counter() - started) * 1000,
            provider="openai-compatible",
            metadata={"model": self.model},
        )


class OpenAICompatibleObservationBackend:
    """OpenAI-compatible low-cost visual observation stage."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_s: float = 60.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_s = timeout_s

    def summarize(self, request: VLMRequest) -> ObservationSummary:
        system_instruction = (
            "You are the low-cost observation stage of an indoor navigation system. "
            "Return only valid JSON with scene, landmarks, and uncertainty. "
            "Do not choose motion, coordinates, or velocity."
        )
        prompt = (
            "Summarize the current RGB-D navigation observation for a higher-level planner. "
            "Use JSON with this shape: {\"scene\": string, "
            "\"landmarks\": [{\"type\": string, \"text\": string, "
            "\"direction\": string|null}], \"uncertainty\": number}.\n\n"
            + request.to_text()
        )
        body = {
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": self._content(request, prompt)},
            ],
        }
        raw_text = self._call(body)
        try:
            payload = json.loads(raw_text)
            scene = str(payload["scene"])
            landmarks = payload.get("landmarks", [])
            uncertainty = payload.get("uncertainty")
            if not isinstance(landmarks, list):
                raise ValueError("landmarks must be a list")
            if uncertainty is not None:
                uncertainty = float(uncertainty)
                if not 0 <= uncertainty <= 1:
                    raise ValueError("uncertainty must be between 0 and 1")
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid observation summary: {exc}") from exc
        return ObservationSummary(
            scene=scene,
            landmarks=landmarks,
            uncertainty=uncertainty,
            raw_text=raw_text,
        )

    def _content(self, request: VLMRequest, prompt: str) -> list[dict[str, Any]]:
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        if request.observation.rgb_path:
            image_url = _image_as_data_url(Path(request.observation.rgb_path))
            if image_url:
                content.append({"type": "image_url", "image_url": {"url": image_url}})
        return content

    def _call(self, body: dict[str, Any]) -> str:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        http_request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=data,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(http_request, timeout=self.timeout_s) as response:
                response_data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"observation VLM HTTP {exc.code}: {detail[:500]}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"observation VLM connection failed: {exc.reason}") from exc
        return _extract_chat_content(response_data)


def navigation_intent_from_json(raw_text: str) -> NavigationIntent:
    """Parse strict JSON, allowing a single markdown code fence."""
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    payload = json.loads(cleaned)
    intent = NavigationIntent(
        intent=IntentType(payload["intent"]),
        motion_owner=MotionOwner(payload["motion_owner"]),
        target=payload.get("target"),
        instruction=payload["instruction"],
        completion_condition=payload["completion_condition"],
        direction=payload.get("direction"),
        distance_hint=payload.get("distance_hint"),
        speed_level=payload.get("speed_level"),
        stop=bool(payload.get("stop", False)),
        reason=payload.get("reason"),
        confidence=payload.get("confidence"),
        metadata=payload.get("metadata", {}),
    )
    errors = intent.validate()
    if errors:
        raise ValueError(f"invalid VLM navigation intent: {errors}")
    return intent


def _extract_chat_content(response_data: dict[str, Any]) -> str:
    try:
        content = response_data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("VLM response has no choices[0].message.content") from exc
    if not isinstance(content, str):
        raise ValueError("VLM message content must be a string")
    return content


def _image_as_data_url(path: Path) -> str | None:
    if not path.exists():
        return None
    mime_type, _ = mimetypes.guess_type(path.name)
    if not mime_type or not mime_type.startswith("image/"):
        return None
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _intent_dict(intent: NavigationIntent) -> dict[str, Any]:
    return {
        "intent": intent.intent.value,
        "motion_owner": intent.motion_owner.value,
        "target": intent.target,
        "instruction": intent.instruction,
        "completion_condition": intent.completion_condition,
        "direction": intent.direction,
        "distance_hint": intent.distance_hint,
        "speed_level": intent.speed_level,
        "stop": intent.stop,
        "reason": intent.reason,
        "confidence": intent.confidence,
    }
