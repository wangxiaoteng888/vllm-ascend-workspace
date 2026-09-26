# PD D-node decode profiling workflow

Use this runbook for a two-node vLLM Ascend PD deployment when the requested
deliverable is a short D-node decode trace and a compact
`D_trace_views_only.tar.gz` archive.

## 1. Resolve the experiment before starting services

Record all of the following in the run directory. Never infer a machine role
from an old run, and never put passwords in the run directory or the skill.

- P host, D host, and how credentials are supplied by the managed environment.
- Container name on both hosts.
- Host workspace and the corresponding path inside the container.
- Shared output filesystem visible from the D container.
- Model path and served model name.
- TP, DP, pipeline, and MTP settings.
- P-node prefix-cache state and D-node prefix-cache state separately.
- D-node recompute-scheduler state.
- `TASK_QUEUE_ENABLE` value on P and D separately.
- Profiler stack setting and requested capture duration.
- Input length, output length, concurrency, number of requests, and whether the
  dataset contains repeated prefixes.
- Whether services should remain running after the capture.

A useful run name is:

```text
pd_<container>_D_profile_<taskqueue>_<recompute>_<cache>_2k2k_c1_n4_decode5s_<stack>_<timestamp>
```

Use this layout:

```text
<run>/
  P_and_proxy/
  D_and_profile/
    profile_raw_D/
  profile_control/
  aisbench/
```

Put raw profiler data on the shared filesystem so parsing does not fill the
container overlay filesystem.

## 2. Configure and launch the PD service

Start from the launch scripts for the requested container version. Save an
exact copy of the effective P command, D command, proxy command, environment,
and logs in the run directory.

For the D node, configure the profiler output path to the shared run directory.
For example, the effective profiler configuration should contain the requested
stack setting explicitly:

```json
{
  "profiler_level": "Level1",
  "with_stack": false,
  "data_simplification": true
}
```

The spelling of the service flags depends on the checked-out vLLM Ascend
version. Verify them from `--help` or the source in that version instead of
copying flags blindly. Record these independently:

- no prefix cache: the P and D launch commands must both omit or disable the
  prefix-cache option;
- recompute scheduler: enable it only on D when the experiment requests it;
- MTP: record the speculative/MTP arguments and effective number of draft
  tokens;
- task queue: export `TASK_QUEUE_ENABLE` in the service process environment,
  not only in an unrelated interactive shell.

Launch the supported PD proxy from the repository, normally
`load_balance_proxy_server_example.py`, with P in the prefiller list and D in
the decoder list. The exact CLI varies by branch; a representative shape is:

```bash
python3 load_balance_proxy_server_example.py \
  --host 0.0.0.0 --port <proxy-port> \
  --prefiller-hosts <P-host> --prefiller-ports <P-port> \
  --decoder-hosts <D-host> --decoder-ports <D-port>
```

Check the P endpoint, D endpoint, and proxy endpoint independently. For a PD
experiment, AISBench must target the proxy. Sending directly to D is a
different mixed/prefill+decode experiment and is only valid when explicitly
requested.

## 3. Prove decode is active before profiling

Do not start the profiler merely five seconds after submitting a request. A
sleep does not prove that the request has reached decode.

1. Start a small warmup request through the proxy.
2. Start the formal 2048-input/2048-output, concurrency-1, four-request
   workload through the proxy.
3. Poll the D node `/metrics` endpoint.
4. Start profiling only after `vllm:generation_tokens_total` increases.
5. Save metrics immediately before and after the capture.
6. Use the metrics delta to identify the active D engine/DP.
7. Stop the profiler and wait until its export has fully completed.

Run the supplied monitor inside an environment that can reach the D endpoint:

```bash
export D_URL=http://<D-host>:<D-port>
export RUN_DIR=<shared-run-directory>
export PROFILE_SECONDS=5
export DECODE_WAIT_SECONDS=900
bash scripts/capture_decode_window.sh
```

The script writes the profile-control responses, the metrics snapshots, and
`D_decode_window_delta.json`. A successful capture requires a positive token delta.
The `active_engines` keys in that JSON are the evidence for the DP/engine that
processed decode. Do not identify a DP merely by finding a populated trace;
dummy batches can also produce trace activity.

## 4. Parse only the required trace output

The raw D profile root should contain one `*_ascend_pt` directory per profiled
rank. Run:

```bash
python3 scripts/analyse_trace_views.py \
  <run>/D_and_profile/profile_raw_D \
  --jobs 4 \
  --expected-ranks <expected-rank-count>
```

The parser invokes `torch_npu.profiler.profiler.analyse` for ranks that do not
already have a non-empty `ASCEND_PROFILER_OUTPUT/trace_view.json`. It writes a
per-rank log and `trace_view_manifest.json`. Run it in the software environment
matching the profiled container/version.

If parsing is slow, reduce `--jobs` when host memory or disk bandwidth is the
limit. Never delete raw data to make parsing faster unless the user explicitly
authorizes that destructive action.

## 5. Build and validate the compact archive

Package only the per-rank trace-view files:

```bash
bash scripts/package_trace_views.sh \
  <run>/D_and_profile/profile_raw_D \
  <run>/D_and_profile \
  <expected-rank-count>
```

The archive layout is:

```text
trace_view/<rank>_ascend_pt/ASCEND_PROFILER_OUTPUT/trace_view.json
```

The script refuses to publish an archive when the number of non-empty trace
views differs from the expected rank count. It also creates:

```text
D_trace_views_only.tar.gz
D_trace_views_only.tar.gz.sha256
```

Before handing off, also keep these files with the run:

- P service log and effective command;
- D service log and effective command;
- proxy log and effective command;
- AISBench warmup/formal console logs and return codes;
- D metrics before/after and `D_decode_window_delta.json`;
- profiler start/stop responses;
- `trace_view_manifest.json` and parser logs;
- the archive and SHA-256 sidecar.

Report the server-side archive path, active D DP/engine, token delta during the
capture, cache/recompute/task-queue/MTP/stack settings, trace count, archive
size, and SHA-256. If the user asks only for the path, return only the path.
