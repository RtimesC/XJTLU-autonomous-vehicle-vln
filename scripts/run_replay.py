#!/usr/bin/env python3
"""Run a deterministic replay without camera, network, or external packages."""

from __future__ import annotations

import argparse
from pathlib import Path

from reasonnav_stage1.contracts import Goal
from reasonnav_stage1.replay import JsonlReplay
from reasonnav_stage1.vlm import MockVLMBackend


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--goal", required=True)
    args = parser.parse_args()

    replay = JsonlReplay(args.input)
    responses = replay.run(
        goal=Goal(type="room", value=args.goal),
        backend=MockVLMBackend(),
    )
    for response in responses:
        print(response.raw_text)


if __name__ == "__main__":
    main()
