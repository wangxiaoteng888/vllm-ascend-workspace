"""Passive SHM notification counters. The reporter never accesses a ZMQ socket."""
import json
import os
import threading
import time
import weakref
from pathlib import Path

_states = weakref.WeakValueDictionary()
_lock = threading.Lock()
_reporter = None
_pid = os.getpid()
_names = ("shm_reads", "wait_calls", "spin_returns", "poll_calls",
          "poll_returns", "notify_recvs", "cancel_events", "poll_timeouts",
          "notify_sends")


class NotifyDiagnostics:
    def __init__(self, owner, address):
        self.created = time.monotonic()
        self.last_read = None
        self.last_poll = None
        self.last_poll_return = None
        self.last_recv = None
        self.queue = hex(id(owner))
        self.address = address
        self.reader = owner.is_reader
        # This property returns the C socket pointer; it does not query EVENTS.
        self.socket_pointer = hex(owner.local_notify_socket.underlying)
        for name in _names:
            setattr(self, name, 0)


def _write_snapshot(stream, previous):
    now = time.monotonic()
    with _lock:
        states = list(_states.values())
    rows = []
    live = set()
    for state in states:
        live.add(state.queue)
        totals = {name: getattr(state, name) for name in _names}
        old = previous.get(state.queue, {})
        row = {
            "queue": state.queue, "notify_address": state.address,
            "reader": state.reader, "socket_pointer": state.socket_pointer,
            "created_mono": state.created, "age_s": now - state.created, "totals": totals,
            "delta": {k: v - old.get(k, 0) for k, v in totals.items()},
        }
        for name in ("last_read", "last_poll", "last_poll_return", "last_recv"):
            stamp = getattr(state, name)
            row[f"since_{name}_s"] = None if stamp is None else now - stamp
        rows.append(row)
        previous[state.queue] = totals
    for key in list(previous):
        if key not in live:
            del previous[key]
    stream.write(json.dumps({
        "event": "shm_notify_diag", "at": time.time(), "pid": os.getpid(),
        "ppid": os.getppid(), "queues": rows,
        "note": "Passive approximate counters; no ZMQ calls from reporter",
    }) + "\n")
    stream.flush()


def _report():
    directory = Path(os.environ["VLLM_NOTIFY_DIAG_DIR"])
    interval = max(1.0, float(os.environ.get("VLLM_NOTIFY_DIAG_INTERVAL", "10")))
    previous = {}
    try:
        directory.mkdir(parents=True, exist_ok=True)
        # PID + start time avoids conflating reused process IDs.
        path = directory / f"notify-{os.getpid()}-{time.time_ns()}.jsonl"
        with path.open("x", encoding="utf-8", buffering=1) as stream:
            while True:
                _write_snapshot(stream, previous)
                time.sleep(interval)
    except Exception as exc:
        # Diagnostic I/O failure must not stop serving.
        print(f"SHM_NOTIFY_DIAG_FAILED pid={os.getpid()} {exc!r}", flush=True)


def new_notify_diagnostics(owner, address):
    global _reporter, _pid, _states, _lock
    if not os.environ.get("VLLM_NOTIFY_DIAG_DIR"):
        return None
    if _pid != os.getpid():
        # Forked children must not report the parent's sockets.
        _pid = os.getpid()
        _states = weakref.WeakValueDictionary()
        _lock = threading.Lock()
        _reporter = None
    state = NotifyDiagnostics(owner, address)
    with _lock:
        _states[state.queue] = state
        if _reporter is None:
            _reporter = threading.Thread(
                target=_report, name="shm-notify-diagnostics", daemon=True
            )
            _reporter.start()
    return state
