"""Opt-in workaround for a VERIFIED six-vs-seven-argument libbcc ABI mismatch.

Not enabled merely because BCC reports a version or because tracing fails.
Only modifies this observer process, never the system BCC installation.
"""
import argparse
import ctypes
import runpy
import sys


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--tool',required=True)
    p.add_argument('--verified-ref-counter-abi',action='store_true',required=True)
    p.add_argument('tool_args',nargs=argparse.REMAINDER)
    a=p.parse_args()
    from bcc.libbcc import lib
    native=lib.bpf_attach_uprobe
    if native.argtypes is None or len(native.argtypes)!=6:
        raise SystemExit('Expected six-argument binding; do not use this shim on another ABI')
    native.argtypes=list(native.argtypes)+[ctypes.c_uint32]
    lib.bpf_attach_uprobe=lambda *args:native(*args,0)
    args=a.tool_args[1:] if a.tool_args[:1]==['--'] else a.tool_args
    sys.argv=[a.tool]+args
    runpy.run_path(a.tool,run_name='__main__')


if __name__=='__main__':main()
