"""Read-only process identity, memory, mapped libraries and BCC prerequisites."""
import argparse
import json
import os
import re
import shutil
import socket
import time
from pathlib import Path
from proc_utils import identity, libraries, sample


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--pid',type=int)
    p.add_argument('--match',default='VLLM::EngineCore')
    p.add_argument('--output')
    a=p.parse_args();rows=[]
    pids=[a.pid] if a.pid else [int(x.name) for x in Path('/proc').iterdir() if x.name.isdigit()]
    for pid in pids:
        if pid==os.getpid():continue
        try:
            ident=identity(pid)
            if not a.pid and not re.search(a.match,ident['cmd']):continue
            item=sample(pid);item['libraries']=libraries(pid)
            item['threads']=[{'tid':int(t.name),'comm':(t/'comm').read_text().strip()} for t in Path(f'/proc/{pid}/task').iterdir()]
            rows.append(item)
        except (OSError,ValueError,RuntimeError) as e:
            if a.pid:rows.append({'pid':pid,'error':repr(e)})
    kernel=os.uname().release
    result={'at':time.time(),'local_time':time.strftime('%Y-%m-%d %H:%M:%S %z'),'host':socket.gethostname(),
            'kernel':kernel,'observer_pid_namespace':os.readlink('/proc/self/ns/pid'),'targets':rows,
            'tools':{k:shutil.which(k) for k in ('memleak-bpfcc','memleak','readelf','objdump','addr2line','bpftool')},
            'bcc_prerequisites':{'uid':os.getuid(),'kernel_build':Path(f'/lib/modules/{kernel}/build').exists(),
                                 'btf_vmlinux':Path('/sys/kernel/btf/vmlinux').exists()}}
    if a.output:Path(a.output).write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
