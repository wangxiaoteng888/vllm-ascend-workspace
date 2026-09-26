#!/usr/bin/env python3
"""Compute per-engine generation-token deltas from two vLLM metrics snapshots."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


METRIC_RE = re.compile(r"^vllm:generation_tokens_total\{([^}]*)\}\s+([0-9.eE+-]+)$")
ENGINE_RE = re.compile(r'engine="([^"]+)"')


def read_metrics(path: Path) -> dict[str, float]:
    values: dict[str, float] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = METRIC_RE.match(line)
        if not match:
            continue
        engine = ENGINE_RE.search(match.group(1))
        if engine:
            engine_id = engine.group(1)
            values[engine_id] = values.get(engine_id, 0.0) + float(match.group(2))
    return values


def engine_sort_key(engine: str) -> tuple[int, int | str]:
    return (0, int(engine)) if engine.isdigit() else (1, engine)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    before = read_metrics(args.before)
    after = read_metrics(args.after)
    engines = sorted(set(before) | set(after), key=engine_sort_key)
    deltas = {engine: after.get(engine, 0.0) - before.get(engine, 0.0) for engine in engines}
    result = {
        "metric": "vllm:generation_tokens_total",
        "total_delta": sum(deltas.values()),
        "active_engines": {engine: value for engine, value in deltas.items() if value > 0},
        "all_engine_deltas": deltas,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, separators=(",", ":")))
    return 0 if result["total_delta"] > 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
