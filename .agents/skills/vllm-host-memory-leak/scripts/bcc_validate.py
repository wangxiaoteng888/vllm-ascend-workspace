"""Verify malloc AND free observation on an isolated disposable worker."""
import argparse
import ctypes
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from bcc_parse import parse_reports


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',required=True)
    p.add_argument('--tool',default='/usr/sbin/memleak-bpfcc')
    p.add_argument('--verified-ref-counter-abi',action='store_true')
    p.add_argument('--worker',action='store_true',help=argparse.SUPPRESS)
    a=p.parse_args();out=Path(a.output)
    size=12347
    if a.worker:
        libc=ctypes.CDLL('libc.so.6');libc.malloc.argtypes=[ctypes.c_size_t];libc.malloc.restype=ctypes.c_void_p;libc.free.argtypes=[ctypes.c_void_p]
        print(json.dumps({'pid':os.getpid()}),flush=True)
        deadline=time.monotonic()+45
        while not (out/'go').exists():
            if time.monotonic()>deadline:raise TimeoutError('No observer ready')
            time.sleep(.1)
        ptrs=[libc.malloc(size) for _ in range(1000)]
        if not all(ptrs):raise MemoryError('Validation malloc failed')
        print(json.dumps({'stage':'1000_live','at':time.time()}),flush=True);time.sleep(8)
        for ptr in ptrs[:900]:libc.free(ptr)
        print(json.dumps({'stage':'100_live','at':time.time()}),flush=True);time.sleep(8)
        for ptr in ptrs[900:]:libc.free(ptr)
        print(json.dumps({'stage':'zero_live','at':time.time()}),flush=True);time.sleep(8)
        return
    out.mkdir(parents=True,exist_ok=False)
    observer=None;worker=None
    with (out/'worker.log').open('w') as w,(out/'stdout.log').open('w') as o,(out/'stderr.log').open('w') as e:
        try:
            worker=subprocess.Popen([sys.executable,'-u',__file__,'--output',str(out),'--worker'],stdout=w,stderr=w)
            cmd=[sys.executable,'-u',a.tool]
            if a.verified_ref_counter_abi:
                cmd=[sys.executable,'-u',str(Path(__file__).with_name('bcc_compat.py')),'--tool',a.tool,'--verified-ref-counter-abi','--']
            cmd+=['-p',str(worker.pid),'-z',str(size),'-Z',str(size),'-o','500','-T','50','2']
            observer=subprocess.Popen(cmd,stdout=o,stderr=e)
            deadline=time.monotonic()+35
            while 'Top ' not in (out/'stdout.log').read_text():
                if observer.poll() is not None:raise RuntimeError('Observer failed; inspect stderr.log')
                if time.monotonic()>deadline:raise TimeoutError('No first BCC report')
                time.sleep(.2)
            (out/'go').touch();worker.wait(timeout=35)
            if worker.returncode:raise RuntimeError('Validation worker failed')
        finally:
            for child in (observer,worker):
                if child is not None and child.poll() is None:
                    child.send_signal(signal.SIGINT)
                    try:child.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        child.kill();child.wait(timeout=5)
    reports=parse_reports((out/'stdout.log').read_text())
    counts=[sum(s['blocks'] for s in r['stacks'] if s['bytes']==s['blocks']*size) for r in reports]
    expected=[1000,100,0];stage=0
    for n in counts:
        if stage<len(expected) and n==expected[stage]:stage+=1
    result={'passed':stage==len(expected),'allocation_size':size,'expected_order':expected,'observed_blocks':counts,
            'scope':'Observer validation only; not evidence that the service leaks'}
    (out/'validation.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
    if not result['passed']:raise SystemExit(2)


if __name__=='__main__':main()
