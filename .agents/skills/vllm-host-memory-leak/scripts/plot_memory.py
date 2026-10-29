"""Plot one process lifetime; reject stale data unless explicitly historical."""
import argparse
import csv
import json
import re
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path


def read_rows(path, fmt, pid, start_ticks=None):
    rows, stamp = [], None
    skipped = 0
    with Path(path).open(encoding='utf-8-sig', errors='replace') as f:
        for line in f:
            if fmt == 'smem':
                if re.fullmatch(r'\d{4}-\d\d-\d\d \d\d:\d\d:\d\d [+-]\d{4}\s*', line):
                    stamp = datetime.strptime(line.strip(), '%Y-%m-%d %H:%M:%S %z').timestamp()
                # Standard columns: PID User Command ... Swap USS PSS RSS.
                parts = line.split()
                if stamp and len(parts) >= 7 and parts[0] == str(pid) and all(x.isdigit() for x in parts[-4:]):
                    rows.append({'at': stamp, 'pid': pid, 'start_ticks': 'unavailable-smem',
                                 **{k: int(v)/1024 for k, v in zip(('Swap', 'USS', 'PSS', 'RSS'), parts[-4:])}})
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                skipped += 1
                continue
            for p in obj.get('processes', []):
                if p['pid'] != pid or (start_ticks is not None and str(p.get('start_ticks')) != str(start_ticks)):
                    continue
                rows.append({'at': obj['at'], 'pid': pid, 'start_ticks': p.get('start_ticks'),
                             'boot_id': p.get('boot_id'),
                             **{k: p[k.lower()+'_kib']/1024 for k in ('USS', 'PSS', 'RSS')}})
    if not rows:
        raise ValueError('No selected PID samples')
    if len({(r.get('boot_id'), r['start_ticks']) for r in rows}) != 1:
        raise ValueError('Multiple process lifetimes; select --start-ticks or separate input files')
    return sorted(rows, key=lambda r:r['at']), skipped


def window_stats(rows, seconds):
    selected = [r for r in rows if r['at'] >= rows[-1]['at']-seconds]
    first, last = selected[0], selected[-1]
    duration = last['at'] - first['at']
    return {'start_at': first['at'], 'end_at': last['at'], 'minutes': duration/60,
            'USS_delta_MiB': last['USS']-first['USS'],
            'net_MiB_per_hour': (last['USS']-first['USS'])*3600/duration if duration else None,
            'USS_min_MiB': min(r['USS'] for r in selected), 'USS_max_MiB': max(r['USS'] for r in selected)}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--input', required=True)
    ap.add_argument('--format', choices=['jsonl', 'smem'], default='jsonl')
    ap.add_argument('--pid', type=int, required=True)
    ap.add_argument('--start-ticks', type=int)
    ap.add_argument('--output', required=True, help='New output prefix; PNG, CSV and summary JSON')
    ap.add_argument('--label', default='EngineCore host memory')
    ap.add_argument('--utc-offset', type=float, default=8)
    ap.add_argument('--load-start', help='ISO 8601 datetime with explicit timezone')
    ap.add_argument('--max-age', type=float, default=180)
    ap.add_argument('--gap-seconds', type=float, default=180)
    ap.add_argument('--recent-hours', type=float, default=4)
    ap.add_argument('--historical', action='store_true', help='Permit stale data; chart explicitly labeled historical')
    ap.add_argument('--font', help='Optional font file for Chinese labels')
    a = ap.parse_args()
    rows, skipped = read_rows(a.input, a.format, a.pid, a.start_ticks)
    age = time.time()-rows[-1]['at']
    if (age > a.max_age or age < -60) and not a.historical:
        raise SystemExit(f'Data stale or host clock skew: age={age:.1f}s. Check host time, monitor, health and load; use --historical only for an explicitly historical chart.')
    out = Path(a.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    paths = [Path(str(out)+ext) for ext in ('.png', '.csv', '.json')]
    if any(p.exists() for p in paths):
        raise SystemExit('Use a new output prefix to preserve old evidence')
    tz = timezone(timedelta(hours=a.utc_offset))
    gaps = [{'from':p['at'], 'to':q['at']} for p,q in zip(rows,rows[1:]) if q['at']-p['at']>a.gap_seconds]
    summary = {'source': str(Path(a.input).resolve()), 'source_format':a.format, 'latest':rows[-1],
               'age_seconds':age,'historical':a.historical,'samples':len(rows),'skipped_json_lines':skipped,
               'gaps':gaps,'last30min':window_stats(rows,1800),'last60min':window_stats(rows,3600),
               'warning':'USS growth is not equivalent to leaked bytes; smem does not prove PID lifetime identity.'}
    paths[2].write_text(json.dumps(summary,indent=2),encoding='utf-8')
    with paths[1].open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    if a.font:
        from matplotlib import font_manager
        font_manager.fontManager.addfont(a.font)
        plt.rcParams['font.family']=font_manager.FontProperties(fname=a.font).get_name()
    fig,axs=plt.subplots(1,2,figsize=(14,6))
    fig.subplots_adjust(top=.75,bottom=.24,wspace=.25)
    for ax,sel,title in [(axs[0],rows,'Full USS history'),(axs[1],[r for r in rows if r['at']>=rows[-1]['at']-a.recent_hours*3600],f'Last {a.recent_hours:g} hours USS')]:
        x=[];y=[];previous=None
        for r in sel:
            if previous is not None and r['at']-previous>a.gap_seconds:
                x.append(datetime.fromtimestamp(r['at'],tz));y.append(float('nan'))
            x.append(datetime.fromtimestamp(r['at'],tz));y.append(r['USS']);previous=r['at']
        ax.plot(x,y,lw=1.5,color='#176b9b');ax.set_title(title,loc='left');ax.set_ylabel('MiB')
        ax.grid(alpha=.2);ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d\n%H:%M',tz=tz))
        ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=3,maxticks=6))
        ax.ticklabel_format(axis='y',style='plain',useOffset=False)
        if a.load_start:
            dt=datetime.fromisoformat(a.load_start)
            if dt.tzinfo is None:raise ValueError('--load-start needs timezone')
            if sel[0]['at']<=dt.timestamp()<=sel[-1]['at']:ax.axvline(dt,color='#c46c24',ls='--')
    last=rows[-1]
    fig.suptitle(a.label + (' [HISTORICAL]' if a.historical else ''),fontsize=19,y=.96)
    fig.text(.125,.84,f"PID {a.pid} | Last sample {datetime.fromtimestamp(last['at'],tz).isoformat(timespec='seconds')}\nUSS {last['USS']:.2f} MiB | PSS {last['PSS']:.2f} MiB | RSS {last['RSS']:.2f} MiB",fontsize=11)
    fig.text(.125,.07,f"Source: {a.format}; sampling gaps > {a.gap_seconds:g}s are not connected.\nHost process memory, not NPU HBM. Growth alone does not prove a leak.",fontsize=10)
    fig.savefig(paths[0],dpi=150);plt.close(fig)
    print(json.dumps(summary,indent=2))


if __name__=='__main__':main()
