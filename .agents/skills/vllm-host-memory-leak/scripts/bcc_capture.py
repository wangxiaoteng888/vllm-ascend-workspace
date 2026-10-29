"""Bounded stock BCC memleak observer. PID belongs to the observer's /proc view."""
import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from proc_utils import atomic_json, digest, identity, libraries, sample, latest_json


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--pid',type=int,required=True)
    p.add_argument('--expected-start-ticks',type=int,required=True,help='From inventory /proc; prevents wrong-lifetime attachment')
    p.add_argument('--seconds',type=int,default=640)
    p.add_argument('--interval',type=int,default=30)
    p.add_argument('--older-ms',type=int,default=1000)
    p.add_argument('--top',type=int,default=100)
    p.add_argument('--sample-rate',type=int,default=1)
    p.add_argument('--min-size',type=int)
    p.add_argument('--max-size',type=int)
    p.add_argument('--tool',default='/usr/sbin/memleak-bpfcc')
    p.add_argument('--python',default='/usr/bin/python3',help='Interpreter that can import bcc')
    p.add_argument('--verified-ref-counter-abi',action='store_true')
    p.add_argument('--notify-file',help='Optional existing log; container PID may differ from observed PID')
    p.add_argument('--load-status',help='Optional workload JSON snapshot')
    p.add_argument('--output',required=True)
    a=p.parse_args()
    if min(a.seconds,a.interval,a.top,a.sample_rate)<=0 or a.older_ms<0:p.error('Invalid duration/options')
    original=identity(a.pid)
    if original['start_ticks']!=a.expected_start_ticks:raise SystemExit('Target start ticks differ')
    tool=Path(a.tool).resolve()
    if not tool.is_file():raise SystemExit('Install BCC for the running kernel; see references/bcc.md')
    out=Path(a.output);out.mkdir(parents=True,exist_ok=False)
    cmd=[a.python,'-u',str(tool)]
    if a.verified_ref_counter_abi:
        shim=Path(__file__).with_name('bcc_compat.py')
        cmd=[a.python,'-u',str(shim),'--tool',str(tool),'--verified-ref-counter-abi','--']
        (out/'bcc_compat.py').write_bytes(shim.read_bytes())
    cmd+=['-p',str(a.pid),'-o',str(a.older_ms),'-T',str(a.top),'-s',str(a.sample_rate)]
    if a.min_size is not None:cmd+=['-z',str(a.min_size)]
    if a.max_size is not None:cmd+=['-Z',str(a.max_size)]
    cmd+=[str(a.interval)]
    meta={'started_at':time.time(),'target':original,'kernel':os.uname().release,
          'arguments':vars(a),'command':cmd,'tool_sha256':digest(tool),
          'libraries':libraries(a.pid),'status':'starting',
          'scope':'Only allocations observed after attachment, still outstanding at report time; top-N and age filters apply. Not total historical heap and not per-socket queue depth.'}
    (out/'maps.start.txt').write_text(Path(f'/proc/{a.pid}/maps').read_text())
    (out/'memleak.source.py').write_bytes(tool.read_bytes())
    atomic_json(out/'metadata.json',meta)
    stop=False;child=None

    def signal_stop(*_):
        nonlocal stop
        stop=True
    signal.signal(signal.SIGINT,signal_stop);signal.signal(signal.SIGTERM,signal_stop)
    try:
        with (out/'stdout.log').open('w') as stdout,(out/'stderr.log').open('w') as stderr,(out/'samples.jsonl').open('w',buffering=1) as samples:
            child=subprocess.Popen(cmd,stdout=stdout,stderr=stderr,start_new_session=True)
            meta.update(observer_pid=child.pid,status='running');atomic_json(out/'metadata.json',meta)
            print(json.dumps({'output':str(out),'observer_pid':child.pid,'target_pid':a.pid}),flush=True)
            deadline=time.monotonic()+a.seconds
            while not stop and child.poll() is None and time.monotonic()<deadline:
                row={'at':time.time()}
                try:
                    proc=sample(a.pid)
                    if (proc['boot_id'],proc['start_ticks'])!=(original['boot_id'],original['start_ticks']):
                        raise RuntimeError('Target lifetime changed')
                    row['process']=proc
                except (OSError,ValueError,RuntimeError) as e:
                    row['error']=repr(e);samples.write(json.dumps(row)+'\n');meta['target_error']=repr(e);break
                for key,path in [('notify',a.notify_file),('load',a.load_status)]:
                    if path:
                        try:row[key]=latest_json(path)
                        except (OSError,ValueError) as e:row[key+'_error']=repr(e)
                samples.write(json.dumps(row)+'\n')
                time.sleep(min(5,max(0,deadline-time.monotonic())))
            if child.poll() is not None:meta['unexpected_observer_exit']=True
    finally:
        if child is not None and child.poll() is None:
            child.send_signal(signal.SIGINT)
            try:child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.terminate()
                try:child.wait(timeout=5)
                except subprocess.TimeoutExpired:child.kill();child.wait(timeout=5)
        meta.update(finished_at=time.time(),observer_exit_code=child.returncode if child else None,
                    status='finished-review-logs')
        atomic_json(out/'metadata.json',meta)
        print(json.dumps(meta),flush=True)
    if meta.get('unexpected_observer_exit') or meta.get('target_error'):raise SystemExit(2)


if __name__=='__main__':main()
