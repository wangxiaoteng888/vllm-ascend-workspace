#!/usr/bin/env python3
"""Copy aisbench_auto_tools_prefix helpers and configure an isolated run."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path


REQUIRED_FILES = {
    "aisbench_test.py",
    "config.py",
    "default_api.py",
    "generate_dataset.py",
    "save_file.py",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tool-dir", required=True, type=Path)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--model-name", required=True)
    parser.add_argument("--model-path", required=True)
    parser.add_argument("--host-ip", required=True)
    parser.add_argument("--host-port", required=True)
    parser.add_argument(
        "--work-path",
        required=True,
        help="AISBench package location reported by `pip show ais-bench-benchmark`",
    )
    parser.add_argument(
        "--pod-info",
        action="append",
        default=[],
        help="Metrics endpoint as host:port; repeat for each PD pod",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace generated helper/config files in an existing run directory",
    )
    return parser.parse_args()


def replace_assignment(text: str, name: str, value: object) -> str:
    pattern = re.compile(rf"(?m)^{re.escape(name)}\s*=.*$")
    replacement = f"{name} = {json.dumps(value, ensure_ascii=False)}"
    updated, count = pattern.subn(lambda _: replacement, text)
    if count != 1:
        raise ValueError(f"expected one assignment for {name}, found {count}")
    return updated


def main() -> int:
    args = parse_args()
    tool_dir = args.tool_dir.expanduser().resolve()
    run_dir = args.run_dir.expanduser().resolve()
    if not tool_dir.is_dir():
        print(f"tool directory does not exist: {tool_dir}", file=sys.stderr)
        return 2

    present = {path.name for path in tool_dir.glob("*.py")}
    missing = sorted(REQUIRED_FILES - present)
    if missing:
        print(f"missing required tool files: {', '.join(missing)}", file=sys.stderr)
        return 3
    if run_dir == tool_dir:
        print("run directory must differ from the shared tool directory", file=sys.stderr)
        return 4
    if run_dir.exists() and any(run_dir.iterdir()) and not args.overwrite:
        print(
            f"run directory is not empty: {run_dir}; pass --overwrite to update generated files",
            file=sys.stderr,
        )
        return 5

    run_dir.mkdir(parents=True, exist_ok=True)
    datasets = run_dir / "datasets"
    outputs = run_dir / "outputs"
    datasets.mkdir(exist_ok=True)
    outputs.mkdir(exist_ok=True)

    copied: list[str] = []
    for source in sorted(tool_dir.glob("*.py")):
        shutil.copy2(source, run_dir / source.name)
        copied.append(source.name)

    config_path = run_dir / "config.py"
    config_text = config_path.read_text(encoding="utf-8")
    values = {
        "DATASET_PATH": str(datasets),
        "WORK_PATH": args.work_path,
        "MODEL_NAME": args.model_name,
        "MODEL_PATH": args.model_path,
        "HOST_IP": args.host_ip,
        "HOST_PORT": str(args.host_port),
        "OUTPUT_DIR": str(outputs),
        "POD_INFO": args.pod_info,
    }
    for name, value in values.items():
        config_text = replace_assignment(config_text, name, value)
    config_path.write_text(config_text, encoding="utf-8", newline="\n")

    snapshot = {
        "tool_dir": str(tool_dir),
        "run_dir": str(run_dir),
        "copied_python_files": copied,
        **values,
    }
    (run_dir / "run_config.json").write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps(snapshot, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
