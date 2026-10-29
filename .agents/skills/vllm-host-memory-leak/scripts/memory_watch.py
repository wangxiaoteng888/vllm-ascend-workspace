"""Append-only Linux USS/PSS/RSS monitor with independent error reporting."""
import argparse
import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from proc_utils import atomic_json, identity, sample


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output', required=True)
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument('--pid', type=int, action='append', help='Repeat to select multiple PIDs in this /proc namespace')
    group.add_argument('--match', help='Regex matched against cmdline; discovery follows new process identities')
    ap.add_argument('--interval', type=float, default=60)
    ap.add_argument('--samples', type=int, default=0, help='0 runs until signalled')
    ap.add_argument('--label', default='')
    ap.add_argument('--resume', action='store_true')
    ap.add_argument('--background', action='store_true')
    a = ap.parse_args()
    if a.interval <= 0 or a.samples < 0:
        ap.error('interval must be positive; samples must be nonnegative')
    out = Path(a.output).resolve()
    if a.background:
        # Child acquires the lock and validates resume. Its errors remain in this log.
        out.parent.mkdir(parents=True, exist_ok=True)
        log = out.parent / (out.name + '-launcher.log')
        args = [x for x in sys.argv[1:] if x != '--background']
        with log.open('ab', buffering=0) as f:
            child = subprocess.Popen([sys.executable, '-u', __file__] + args,
                                     stdin=subprocess.DEVNULL, stdout=f, stderr=f, start_new_session=True)
        print(json.dumps({'observer_pid': child.pid, 'log': str(log), 'status': 'starting; verify status.json freshness'}))
        return
    import fcntl
    import resource
    out.mkdir(parents=True, exist_ok=a.resume)
    lock = (out / 'monitor.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    if soft < 65536:
        resource.setrlimit(resource.RLIMIT_NOFILE, (65536 if hard == resource.RLIM_INFINITY else min(65536, hard), hard))
    (out / 'monitor.pid').write_text(str(os.getpid()))
    fixed = {pid: identity(pid) for pid in (a.pid or [])}
    regex = re.compile(a.match) if a.match else None
    atomic_json(out / 'monitor.json', {'observer': identity(os.getpid()), 'started_at': time.time(),
                                      'host': socket.gethostname(), 'arguments': vars(a)})
    stopped = False

    def stop(*_):
        nonlocal stopped
        stopped = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    count = 0
    # Health/metrics are deliberately not queried in the sampling loop.
    # A malformed HTTP response must not terminate memory collection.
    with (out / 'memory.jsonl').open('a', encoding='utf-8', buffering=1) as log:
        while not stopped:
            began = time.monotonic()
            row = {'at': time.time(), 'host': socket.gethostname(), 'label': a.label,
                   'processes': [], 'errors': []}
            pids = list(fixed)
            if regex:
                pids = []
                for p in Path('/proc').iterdir():
                    if p.name.isdigit() and int(p.name) != os.getpid():
                        try:
                            if regex.search(identity(int(p.name))['cmd']):
                                pids.append(int(p.name))
                        except (OSError, ValueError):
                            pass
            for pid in pids:
                try:
                    item = sample(pid)
                    old = fixed.get(pid)
                    if old and (old['boot_id'], old['start_ticks']) != (item['boot_id'], item['start_ticks']):
                        raise RuntimeError('PID reused; refusing to join different lifetimes')
                    row['processes'].append(item)
                except (OSError, ValueError, RuntimeError) as e:
                    row['errors'].append({'pid': pid, 'error': repr(e)})
            row['sample_duration_s'] = time.monotonic() - began
            log.write(json.dumps(row) + '\n')
            state = {'at': time.time(), 'sample_at': row['at'], 'observer_pid': os.getpid(),
                     'status': 'running', 'matched': len(row['processes']), 'errors': row['errors']}
            atomic_json(out / 'status.json', state)
            count += 1
            if a.samples and count >= a.samples:
                break
            while not stopped and time.monotonic() < began + a.interval:
                time.sleep(min(1, max(0, began + a.interval - time.monotonic())))
    state.update(status='stopped', at=time.time())
    atomic_json(out / 'status.json', state)


if __name__ == '__main__':
    main()
