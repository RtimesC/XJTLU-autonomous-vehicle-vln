#!/usr/bin/env python3
"""Start the local first-stage ReasonNav UI with a deterministic replay."""

from __future__ import annotations

import argparse
from pathlib import Path

from reasonnav_stage1.contracts import Goal
from reasonnav_stage1.replay import JsonlReplay
from reasonnav_stage1.runtime import EpisodeRunner, EpisodeStore
from reasonnav_stage1.vlm import MockVLMBackend
from reasonnav_stage1.web_app import serve


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--goal", required=True)
    parser.add_argument("--runs", type=Path, default=Path("runs"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    replay = JsonlReplay(args.input)
    runner = EpisodeRunner(
        goal=Goal(type="room", value=args.goal),
        backend=MockVLMBackend(),
        frames=iter(replay.frames()),
        store=EpisodeStore(args.runs),
    )
    serve(runner, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
