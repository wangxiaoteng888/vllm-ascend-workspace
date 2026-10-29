"""Linux /proc helpers; no torch/vLLM imports and no calls into the target."""
import hashlib
import json
import os
import time
from pathlib import Path


def identity(pid):
    p = Path('/proc') / str(pid)
    raw = (p / 'stat').read_text()
    tail = raw[raw.rfind(')') + 2:].split()
    status = (p / 'status').read_text().splitlines()
    ns = next((x.split()[1:] for x in status if x.startswith('NSpid:')), [])
    return {'pid': int(pid), 'start_ticks': int(tail[19]), 'ppid': int(tail[1]),
            'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
            'pid_namespace': os.readlink(p / 'ns/pid'), 'nspid': [int(x) for x in ns],
            'cmd': (p / 'cmdline').read_bytes().replace(b'\0', b' ').decode(errors='replace').strip()}


def memory(pid):
    values = {}
    for line in (Path('/proc') / str(pid) / 'smaps_rollup').read_text().splitlines():
        if ':' in line:
            key, value = line.split(':', 1)
            if value.strip().endswith('kB'):
                values[key] = int(value.split()[0])
    return {'rss_kib': values.get('Rss', 0), 'pss_kib': values.get('Pss', 0),
            'uss_kib': sum(values.get(k, 0) for k in ('Private_Clean', 'Private_Dirty', 'Private_Hugetlb')),
            'swap_kib': values.get('Swap', 0)}


def sample(pid):
    before = identity(pid)
    result = memory(pid)
    after = identity(pid)
    if (before['boot_id'], before['start_ticks']) != (after['boot_id'], after['start_ticks']):
        raise RuntimeError('PID identity changed during memory read')
    return dict(before, **result)


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def atomic_json(path, obj):
    path = Path(path)
    tmp = path.with_name(path.name + f'.{os.getpid()}.tmp')
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(tmp, path)


def libraries(pid, pattern='libzmq'):
    """Hash the files as seen through the target mount namespace."""
    rows = {}
    for line in (Path('/proc') / str(pid) / 'maps').read_text().splitlines():
        parts = line.split(None, 5)
        if len(parts) != 6 or pattern not in parts[5]:
            continue
        name = parts[5]
        if name in rows:
            continue
        row = {'mapped_path': name}
        try:
            row['sha256'] = digest(Path(f'/proc/{pid}/root') / name.lstrip('/'))
        except OSError as e:
            row['error'] = repr(e)
        rows[name] = row
    return list(rows.values())


def latest_json(path):
    """Read last complete JSON record; don't load a long-running log in memory."""
    path = Path(path)
    with path.open('rb') as f:
        size = f.seek(0, 2)
        f.seek(max(0, size - 2 * 1024 * 1024))
        lines = f.read().splitlines()
    for line in reversed(lines):
        try:
            return json.loads(line)
        except (ValueError, UnicodeDecodeError):
            pass
    raise ValueError(f'No complete JSON record in {path}')
