#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 || $# -gt 3 ]]; then
    echo "usage: $0 PROFILE_ROOT OUTPUT_DIR [EXPECTED_RANKS]" >&2
    exit 2
fi

profile_root="$(realpath "$1")"
output_dir="$(realpath -m "$2")"
expected_ranks="${3:-16}"
output_path="${output_dir}/D_trace_views_only.tar.gz"
stage_dir="$(mktemp -d)"
trap 'rm -rf -- "$stage_dir"' EXIT

mapfile -d '' rank_dirs < <(find "$profile_root" -mindepth 1 -maxdepth 1 -type d -name '*_ascend_pt' -print0)
if [[ "${#rank_dirs[@]}" -ne "$expected_ranks" ]]; then
    echo "expected ${expected_ranks} rank directories, found ${#rank_dirs[@]}" >&2
    exit 3
fi

for rank_dir in "${rank_dirs[@]}"; do
    trace_path="${rank_dir}/ASCEND_PROFILER_OUTPUT/trace_view.json"
    [[ -s "$trace_path" ]] || {
        echo "missing or empty trace: ${trace_path}" >&2
        exit 4
    }
    rank_name="$(basename "$rank_dir")"
    target_dir="${stage_dir}/trace_view/${rank_name}/ASCEND_PROFILER_OUTPUT"
    mkdir -p "$target_dir"
    cp -- "$trace_path" "${target_dir}/trace_view.json"
done

mkdir -p "$output_dir"
tar -czf "$output_path" -C "$stage_dir" trace_view
sha256sum "$output_path" >"${output_path}.sha256"

archive_count="$(tar -tzf "$output_path" | grep -c '/trace_view.json$' || true)"
if [[ "$archive_count" -ne "$expected_ranks" ]]; then
    echo "archive validation failed: expected ${expected_ranks} traces, found ${archive_count}" >&2
    exit 5
fi

python3 - "$output_path" "$archive_count" <<'PY'
import json
import sys
from pathlib import Path

archive = Path(sys.argv[1])
checksum = Path(f"{archive}.sha256").read_text(encoding="utf-8").split()[0]
print(json.dumps({
    "status": "ok",
    "archive": str(archive),
    "trace_count": int(sys.argv[2]),
    "archive_bytes": archive.stat().st_size,
    "sha256": checksum,
    "sha256_file": f"{archive}.sha256",
}, separators=(",", ":")))
PY
