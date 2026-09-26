#!/usr/bin/env python3
"""Parse every Ascend rank directory and validate trace_view.json output."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import subprocess
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("profile_root", type=Path)
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--expected-ranks", type=int, default=16)
    args = parser.parse_args()

    root = args.profile_root.resolve()
    rank_dirs = sorted(path for path in root.rglob("*_ascend_pt") if path.is_dir())
    log_dir = root.parent / f"{root.name}_trace_view_analysis_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    code = (
        "import sys; from torch_npu.profiler.profiler import analyse; "
        "analyse(sys.argv[1], max_process_number=4, export_type='text')"
    )

    def analyse_one(item: tuple[int, Path]) -> dict[str, object]:
        index, rank_dir = item
        output = rank_dir / "ASCEND_PROFILER_OUTPUT"
        trace = output / "trace_view.json"
        log_path = log_dir / f"rank_{index:02d}.log"
        if trace.is_file() and trace.stat().st_size > 0:
            return {
                "index": index,
                "rank_dir": str(rank_dir),
                "return_code": 0,
                "reused": True,
                "trace_view": str(trace),
                "trace_view_exists": True,
                "trace_view_bytes": trace.stat().st_size,
                "trace_view_valid": True,
                "log": str(log_path),
            }
        with log_path.open("wb") as log:
            result = subprocess.run(
                [sys.executable, "-c", code, str(rank_dir)],
                stdout=log,
                stderr=subprocess.STDOUT,
                check=False,
            )
        trace_valid = trace.is_file() and trace.stat().st_size > 0
        return {
            "index": index,
            "rank_dir": str(rank_dir),
            "return_code": result.returncode,
            "reused": False,
            "trace_view": str(trace),
            "trace_view_exists": trace.is_file(),
            "trace_view_bytes": trace.stat().st_size if trace.is_file() else 0,
            "trace_view_valid": trace_valid,
            "log": str(log_path),
        }

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        rows = list(pool.map(analyse_one, enumerate(rank_dirs)))

    manifest = {
        "profile_root": str(root),
        "expected_ranks": args.expected_ranks,
        "rank_count": len(rank_dirs),
        "trace_view_count": sum(bool(row["trace_view_valid"]) for row in rows),
        "all_ok": len(rank_dirs) == args.expected_ranks
        and all(row["return_code"] == 0 and row["trace_view_valid"] for row in rows),
        "ranks": rows,
    }
    manifest_path = root.parent / f"{root.name}_trace_view_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0 if manifest["all_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
