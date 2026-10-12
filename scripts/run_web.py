#!/usr/bin/env python3
"""Start the local first-stage ReasonNav UI with a deterministic replay."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from reasonnav_stage1.contracts import Goal
from reasonnav_stage1.replay import JsonlReplay
from reasonnav_stage1.runtime import EpisodeRunner, EpisodeStore
from reasonnav_stage1.vlm import (
    MockVLMBackend,
    OpenAICompatibleObservationBackend,
    OpenAICompatibleVLM,
    TieredVLMBackend,
)
from reasonnav_stage1.web_app import serve


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--goal", required=True)
    parser.add_argument(
        "--backend",
        choices=("mock", "api", "tiered"),
        default=os.getenv("REASONNAV_BACKEND", "mock"),
        help="mock for offline replay, api for one planner, tiered for cheap observation + strong planner",
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("REASONNAV_API_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
    )
    parser.add_argument("--api-key-env", default="REASONNAV_API_KEY")
    parser.add_argument(
        "--planner-model",
        default=os.getenv("REASONNAV_PLANNER_MODEL", "qwen3-vl-plus"),
    )
    parser.add_argument(
        "--fast-model",
        default=os.getenv("REASONNAV_FAST_MODEL", "qwen3-vl-8b-instruct"),
    )
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--runs", type=Path, default=Path("runs"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    if args.backend == "mock":
        backend = MockVLMBackend()
    else:
        api_key = os.getenv(args.api_key_env)
        if not api_key:
            parser.error(
                f"API backend requires environment variable {args.api_key_env}; "
                "use --backend mock for offline replay"
            )
        planner = OpenAICompatibleVLM(
            base_url=args.base_url,
            api_key=api_key,
            model=args.planner_model,
            timeout_s=args.timeout,
        )
        if args.backend == "api":
            backend = planner
        else:
            backend = TieredVLMBackend(
                observer=OpenAICompatibleObservationBackend(
                    base_url=args.base_url,
                    api_key=api_key,
                    model=args.fast_model,
                    timeout_s=args.timeout,
                ),
                planner=planner,
            )

    replay = JsonlReplay(args.input)
    runner = EpisodeRunner(
        goal=Goal(type="room", value=args.goal),
        backend=backend,
        frames=iter(replay.frames()),
        store=EpisodeStore(args.runs),
    )
    serve(runner, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
