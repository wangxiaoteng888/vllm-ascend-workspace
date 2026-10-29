"""Parse memleak printed reports without assuming a binary's symbol offsets."""
import argparse
import json
import re
from pathlib import Path


def parse_reports(text, maps=''):
    mappings=[]
    for line in maps.splitlines():
        p=line.split(None,5)
        if len(p)==6:
            lo,hi=(int(x,16) for x in p[0].split('-'))
            mappings.append((lo,hi,int(p[2],16),p[5]))
    reports=[]
    for seg in re.split(r'(?=\[\d\d:\d\d:\d\d\] Top)',text)[1:]:
        stamp=re.match(r'\[(.*?)\]',seg)[1]
        stacks=[]
        for b in re.split(r'(?=^[ \t]*\d+ bytes in \d+ allocations from stack)',seg,flags=re.MULTILINE):
            m=re.match(r'\s*(\d+) bytes in (\d+) allocations from stack',b)
            if not m:continue
            frames=[]
            for line in b.splitlines()[1:]:
                f=re.match(r'\s*(0x[0-9a-fA-F]+)\s+(.+)',line)
                if not f:continue
                address=int(f[1],16);frame={'address':f[1],'symbol':f[2]}
                match=next((x for x in mappings if x[0]<=address<x[1]),None)
                if match:
                    frame.update(library=match[3],file_offset=hex(address-match[0]+match[2]))
                frames.append(frame)
            stacks.append({'bytes':int(m[1]),'blocks':int(m[2]),'frames':frames})
        reports.append({'time_of_day':stamp,'stacks':stacks})
    return reports


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--capture',required=True)
    p.add_argument('--library',default='libzmq',help='Substring, not proof of a specific queue')
    p.add_argument('--frame-file-offset',help='Optional verified file offset, e.g. 0x123; never copy from another build')
    p.add_argument('--output',required=True)
    a=p.parse_args();base=Path(a.capture)
    reports=parse_reports((base/'stdout.log').read_text(errors='replace'),(base/'maps.start.txt').read_text())
    summaries=[]
    for report in reports:
        selected=[]
        for s in report['stacks']:
            if any(a.library in (f.get('library','')+' '+f['symbol']) and
                   (a.frame_file_offset is None or f.get('file_offset')==hex(int(a.frame_file_offset,0))) for f in s['frames']):
                selected.append(s)
        summaries.append({'time_of_day':report['time_of_day'],'printed_stack_count':len(report['stacks']),
                          'selected_printed_bytes':sum(s['bytes'] for s in selected),
                          'selected_printed_blocks':sum(s['blocks'] for s in selected),'selected_stacks':selected})
    result={'capture':str(base.resolve()),'filters':vars(a),'reports':summaries,
            'stderr':(base/'stderr.log').read_text(errors='replace'),
            'limitations':['Zero selected stacks can mean absent from top-N, not zero outstanding allocations.',
                          'File offsets are not necessarily ELF virtual addresses; inspect PT_LOAD before addr2line/objdump.',
                          'Separate captures have different allocation cohorts; do not subtract their endpoints as historical backlog.',
                          'Time-of-day must be aligned with metadata/timezone, including midnight.']}
    Path(a.output).write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({'reports':len(summaries),'last':summaries[-1] if summaries else None},indent=2))


if __name__=='__main__':main()
