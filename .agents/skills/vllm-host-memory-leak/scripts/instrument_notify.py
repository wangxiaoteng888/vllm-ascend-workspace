"""Version-sensitive passive SpinCondition instrumentation; preview is default."""
import argparse
import ast
import difflib
import hashlib
import json
import os
from pathlib import Path
import shutil
from proc_utils import digest

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--target',help='Exact shm_broadcast.py path from the serving interpreter')
p.add_argument('--output',help='New evidence directory')
p.add_argument('--expected-sha256',help='Required for --apply')
p.add_argument('--apply',action='store_true')
p.add_argument('--restore',help='installation.json from a prior apply')
a=p.parse_args()
root=Path(__file__).resolve().parent
if a.restore:
    manifest=json.loads(Path(a.restore).read_text())
    if not manifest.get('applied'):raise SystemExit('Manifest is not an applied installation')
    target=Path(manifest['target']);helper=Path(manifest['helper'])
    if digest(target)!=manifest['instrumented_sha256'] or digest(helper)!=manifest['helper_sha256']:
        raise SystemExit('Files changed after installation; inspect rather than overwriting')
    backup=Path(manifest['backup'])
    if digest(backup)!=manifest['baseline_sha256']:raise SystemExit('Backup hash mismatch')
    shutil.copy2(backup,target)
    helper.unlink()
    print(json.dumps({'restored':str(target),'note':'Existing processes keep imported code; restart only within authorized scope'}))
    raise SystemExit(0)
if not a.target or not a.output:p.error('--target and --output are required')
target=Path(a.target).resolve();helper=target.with_name('_notify_diagnostics.py')
original=target.read_text()
if 'from ._notify_diagnostics import new_notify_diagnostics' in original:
    raise SystemExit('Already instrumented; preserve existing baseline')
if a.apply and (not a.expected_sha256 or digest(target)!=a.expected_sha256):
    raise SystemExit('--apply requires matching --expected-sha256')
if helper.exists():raise SystemExit('Helper exists; inspect ownership before replacing it')
updated = original


def replace_once(old, new):
    global updated
    assert updated.count(old) == 1, (old, updated.count(old))
    updated = updated.replace(old, new, 1)


replace_once(
    "class SpinCondition:\n",
    "from ._notify_diagnostics import new_notify_diagnostics\n\n\nclass SpinCondition:\n",
)
replace_once(
    "    def record_read(self):\n        self.last_read = time.monotonic()\n",
    """        self._notify_diag = new_notify_diagnostics(self, notify_address)

    def record_read(self):
        self.last_read = time.monotonic()
        diag = self._notify_diag
        if diag is not None:
            diag.shm_reads += 1
            diag.last_read = self.last_read
""",
)
replace_once(
    '        assert self.is_reader, "Only readers can wait"\n',
    '''        assert self.is_reader, "Only readers can wait"
        diag = self._notify_diag
        if diag is not None:
            diag.wait_calls += 1
''',
)
replace_once(
    "        if current_time <= self.last_read + self.busy_loop_s:\n            sched_yield()\n",
    """        if current_time <= self.last_read + self.busy_loop_s:
            if diag is not None:
                diag.spin_returns += 1
            sched_yield()
""",
)
replace_once(
    "            events = dict(self.poller.poll(timeout=timeout_ms))\n",
    """            if diag is not None:
                diag.poll_calls += 1
                diag.last_poll = current_time
            events = dict(self.poller.poll(timeout=timeout_ms))
            if diag is not None:
                diag.poll_returns += 1
                diag.last_poll_return = time.monotonic()
""",
)
replace_once(
    '                logger.debug("Poller received cancel event")\n',
    '''                if diag is not None:
                    diag.cancel_events += 1
                logger.debug("Poller received cancel event")
''',
)
replace_once(
    "                self.local_notify_socket.recv(flags=zmq.NOBLOCK, copy=False)\n",
    """                self.local_notify_socket.recv(flags=zmq.NOBLOCK, copy=False)
                if diag is not None:
                    diag.notify_recvs += 1
                    diag.last_recv = time.monotonic()
""",
)
replace_once(
    '                logger.debug("Poller timed out")\n',
    '''                if diag is not None:
                    diag.poll_timeouts += 1
                logger.debug("Poller timed out")
''',
)
replace_once(
    '        self.local_notify_socket.send(b"\\x00")\n',
    '''        self.local_notify_socket.send(b"\\x00")
        diag = self._notify_diag
        if diag is not None:
            diag.notify_sends += 1
''',
)
ast.parse(updated)
ast.parse((root / "_notify_diagnostics.py").read_text())
out=Path(a.output).resolve()
out.mkdir(parents=True,exist_ok=False)
backup=out/'shm_broadcast.baseline.py';shutil.copy2(target,backup)
patch=''.join(difflib.unified_diff(original.splitlines(True),updated.splitlines(True),fromfile=str(target)+'.baseline',tofile=str(target)))
(out/'instrumentation.patch').write_text(patch)
manifest={'target':str(target),'helper':str(helper),'backup':str(backup),
          'baseline_sha256':digest(target),'instrumented_sha256':hashlib.sha256(updated.encode()).hexdigest(),
          'helper_sha256':digest(root/'_notify_diagnostics.py'),'applied':False,
          'scope':'Passive approximate counters; no extra ZMQ calls. No service restart performed.'}
(out/'installation.json').write_text(json.dumps(manifest,indent=2))
if a.apply:
    if digest(target)!=manifest['baseline_sha256']:raise SystemExit('Target changed during preparation')
    shutil.copy2(root/'_notify_diagnostics.py',helper)
    tmp=target.with_name(target.name+'.notify-tmp')
    try:
        tmp.write_text(updated);os.replace(tmp,target)
    except Exception:
        helper.unlink()
        raise
    manifest['applied']=True
    (out/'installation.json').write_text(json.dumps(manifest,indent=2))
print(json.dumps(manifest,indent=2))
