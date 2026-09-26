---
name: pd-decode-profiling
description: Collect a short D-node decode profile from a two-node vLLM Ascend PD deployment, prove that decode was active, parse per-DP trace_view.json files, and build a validated D_trace_views_only.tar.gz. Use for PD profiling requests that specify P/D nodes, proxy routing, prefix-cache or recompute settings, task-queue mode, stack collection, and a decode capture window. Do not use for ordinary single-node profiling or profile interpretation.
---

# PD Decode Profiling

Produce a trace-only D-node archive from a real request routed through the PD proxy. Preserve the requested container, model, cache, recompute, MTP, task-queue, concurrency, and stack settings exactly.

## Required outcome

- P and D services use the requested configuration and the official `load_balance_proxy_server_example.py` route.
- The workload goes through the proxy. Do not send it directly to D unless the user explicitly asks for mixed-step/direct-D testing.
- Start profiling only after D's `vllm:generation_tokens_total` increases.
- Record generation-token deltas during the entire capture window. A positive delta is the proof that decode occurred; report the active D engine/DP IDs from that evidence.
- Parse every expected D rank and package only `trace_view.json` files as `D_trace_views_only.tar.gz`.
- Validate the archive member count and write a SHA256 sidecar before reporting success.

## Workflow

1. Read [references/pd-decode-workflow.md](references/pd-decode-workflow.md) before operating a live two-node deployment.
2. Resolve P/D roles from the current request and inspected launch scripts. Never infer roles from IP ordering or an older run.
3. Snapshot the exact launch commands and create a unique run directory. Put profiler raw output on a shared, high-capacity filesystem.
4. Start D with its profiler configuration, then P and the proxy; require both service health endpoints and proxy health.
5. Warm up when requested or when matching a prior performance protocol.
6. Start [scripts/capture_decode_window.sh](scripts/capture_decode_window.sh), then launch the formal workload. The capture script waits for decode, profiles for the configured interval, stops profiling, and records per-engine token deltas.
7. Run [scripts/analyse_trace_views.py](scripts/analyse_trace_views.py) inside the same container/runtime that created the profile.
8. Run [scripts/package_trace_views.sh](scripts/package_trace_views.sh) against the parsed profile root.
9. Verify workload return code, profile-control return code, expected rank count, trace count, archive count, and checksum.

## Operational invariants

- `torch_profiler_with_stack` must match the user's wording: “带调用栈” means `true`; “关闭调用栈采集” means `false`.
- Prefix cache and recompute are independent P/D settings. Record each node's effective flags instead of summarizing them as one global value.
- `TASK_QUEUE_ENABLE` is a process-start environment variable. Apply it to exactly the nodes requested; if the request says only “添加” without narrowing the node, preserve the comparison protocol and record both P and D values.
- For MTP, record the complete speculative config, including `method` and `num_speculative_tokens`.
- A 5-second sleep alone does not prove a decode capture. Success requires a positive token delta measured before and after the window.
- Profiler start/stop can be slow. Do not stop the service, kill the container, or declare failure while `/stop_profile` is still producing output.
- Do not kill unrelated containers or processes. Service cleanup follows the user's explicit lifecycle request; otherwise report the running state.
- Keep credentials out of scripts, logs, skill files, and final answers. Use managed endpoints or transient secret input.

## Handoff

When the user asks only for the archive path, return only the absolute path. Otherwise also report active D DP IDs, capture-window token delta, stack mode, task-queue mode, cache/recompute/MTP settings, trace count, archive size, and SHA256.
