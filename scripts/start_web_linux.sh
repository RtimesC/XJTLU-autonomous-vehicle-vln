#!/usr/bin/env bash
set -euo pipefail

if ! command -v python3 >/dev/null 2>&1; then
  echo "错误：找不到 python3。请先安装 Python 3.10 或更高版本。" >&2
  exit 127
fi

if [[ $# -ne 1 ]]; then
  echo "用法：$0 <目标房间号>" >&2
  echo "示例：$0 4205" >&2
  exit 2
fi

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
project_root="$(cd -- "${script_dir}/.." && pwd)"
cd -- "${project_root}"

PYTHONPATH=src exec python3 scripts/run_web.py \
  --input examples/replay_episode.jsonl \
  --goal "$1"
