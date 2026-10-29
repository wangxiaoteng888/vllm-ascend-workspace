"""Summarize per-queue counters; never call a target socket or equate send-recv with depth."""
import argparse
import json
from pathlib import Path


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',required=True,help='One notify-PID-session.jsonl; do not concatenate sessions')
    p.add_argument('--since',type=float,help='UTC epoch seconds')
    p.add_argument('--until',type=float,help='UTC epoch seconds')
    p.add_argument('--output',required=True)
    a=p.parse_args();first={};last={};pids=set();start=None;end=None
    for line in Path(a.input).open(encoding='utf-8-sig'):
        try:r=json.loads(line)
        except ValueError:continue
        if a.since is not None and r['at']<a.since:continue
        if a.until is not None and r['at']>a.until:continue
        pids.add(r['pid']);start=r['at'] if start is None else start;end=r['at']
        for q in r['queues']:
            key=(q['queue'],q.get('socket_pointer'),q['notify_address'],q.get('created_mono'))
            if key in last and any(v<last[key]['totals'].get(k,0) for k,v in q['totals'].items()):
                raise SystemExit('Counter reset/object reuse detected; split observation window')
            first.setdefault(key,q);last[key]=q
    if len(pids)!=1 or start is None:raise SystemExit('Expected one process session with records')
    queues=[]
    for key,q in last.items():
        delta={k:v-first[key]['totals'].get(k,0) for k,v in q['totals'].items()}
        queues.append({'queue':q['queue'],'socket_pointer':q.get('socket_pointer'),
                       'notify_address':q['notify_address'],'reader':q['reader'],
                       'first_totals':first[key]['totals'],'last_totals':q['totals'],'delta':delta,
                       'observed_reads_without_poll':bool(q['reader'] and delta.get('shm_reads',0)>0 and delta.get('poll_calls',0)==0)})
    result={'input':a.input,'pid':next(iter(pids)),'start_at':start,'end_at':end,'queues':queues,
            'limitations':'Approximate Python counters; send completion is not delivery, recv count is not internal command count. poll=0 only for selected interval; not proof of queue byte growth.'}
    Path(a.output).write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))


if __name__=='__main__':main()
