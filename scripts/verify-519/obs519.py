"""Task 519: where and when a standby Claude member's last turn reaches its record files (read only).

Run with a python that imports graftling (the production .venv-runtime, as `python -I -B`), so the Session reading
below is the code session_read runs (graftling control.py session_read: find_session + read_events).

  obs519.py snap <label> <swarm root> <native session> <transcript> <markers,> <out.json>
      One observation of both record files of one Claude Session:
        - graftling archive <swarm root>/sessions/<sha256>/session.jsonl (found as session_read finds it) and
        - the Claude transcript <transcript>.
      Per file: size, mtime, inode, line count, sha256 of the first 4096 bytes, the first line's length (the archive's
      metadata line: header, pending drafts, observations, source positions), and for each marker every line holding it
      (line number, byte offset of that line, record time, record type). Then session_read's reading of the archive:
      read_events(search=<marker>) with content text and all (hits, last hit index/seq/type), total events, revision.
  obs519.py compare <earlier.json> <later.json>
      Rewrite and shift checks between two observations, and the verdict lines (H1 latency / H2 archive rewrite /
      H3 transcript rewrite). Exit 0 always (an observation, not a gate).
  obs519.py member <swarm root>
      '<agent> <name> <session>' of each Claude agent record in <swarm root>/control/agents (oldest first).
  obs519.py sim <dir> first|resume [marker]
      Rehearsal only, no model: drives graftling's own ClaudeJsonlCollector over a synthetic transcript: 'first' is a
      first turn (marker, default SIM519-M1) then standby; 'resume' a resumed turn (default SIM519-M2). Writes <dir>/swarm and
      <dir>/native.jsonl; the native session id is 's'. The real steps never call it.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


def iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'


def record_time(record: object) -> str:
    """The record's own time: a Claude transcript 'timestamp', or an archive event's epoch-ms 'time'."""
    if not isinstance(record, dict):
        return ''
    if isinstance(record.get('timestamp'), str):
        return record['timestamp']
    if isinstance(record.get('time'), (int, float)) and record['time'] > 0:
        return iso(record['time'] / 1000)
    return ''


def file_view(path: Path, markers: list[str]) -> dict:
    if not path.is_file():
        return {'path': str(path), 'exists': False}
    data = path.read_bytes()
    status = path.stat()
    lines = data.split(b'\n')
    if lines and lines[-1] == b'':
        lines.pop()
    found = {m: [] for m in markers}
    offset = 0
    for number, raw in enumerate(lines, 1):
        text = raw.decode('utf-8', 'replace')
        for marker in markers:
            if marker in text:
                try:
                    record = json.loads(text)
                except ValueError:
                    record = None
                kind = record.get('type') if isinstance(record, dict) else None
                found[marker].append({'line': number, 'offset': offset, 'time': record_time(record), 'type': kind,
                                      'metadata_line': number == 1 and isinstance(record, dict)
                                      and 'archiveVersion' in record})
        offset += len(raw) + 1
    last_time = ''
    for raw in reversed(lines):
        try:
            last_time = record_time(json.loads(raw)) or ''
        except ValueError:
            continue
        if last_time:
            break
    return {'path': str(path), 'exists': True, 'size': status.st_size, 'mtime': iso(status.st_mtime),
            'inode': status.st_ino, 'lines': len(lines),
            'head4096_sha256': hashlib.sha256(data[:4096]).hexdigest()[:16], 'head_len': min(len(data), 4096),
            'line1_bytes': len(lines[0]) if lines else 0, 'last_record_time': last_time, 'markers': found}


def session_read_view(root: Path, session: str, markers: list[str]) -> tuple[dict, Path | None]:
    try:
        from graftling.sessions.reading import find_session, read_events
    except Exception as error:  # noqa: BLE001 - reported, not raised
        return {'error': f'graftling not importable: {error}'}, None
    try:
        store = find_session(root, session)
    except Exception as error:  # noqa: BLE001
        return {'error': f'find_session: {type(error).__name__}: {error}'}, None
    if store is None:
        return {'error': 'find_session: no archive (not-found)'}, None
    view = {'archive_id': store.header.get('id'), 'revision': store.revision, 'events': len(store.events())}
    for marker in markers:
        for content in ('text', 'all'):
            try:
                doc = read_events(store, content=content, search=marker)
            except Exception as error:  # noqa: BLE001
                view[f'{marker}/{content}'] = f'error: {error}'
                continue
            hits = doc.get('hits') or []
            last = hits[-1] if hits else {}
            view[f'{marker}/{content}'] = {'hits': len(hits), 'total': doc.get('total'),
                                           'last_hit': {k: last.get(k) for k in ('index', 'seq', 'type')} if last else None}
    return view, store.path


def snap(label: str, root: str, session: str, transcript: str, markers: str, out: str) -> int:
    names = [m for m in markers.split(',') if m]
    taken = time.time()
    reading, archive = session_read_view(Path(root), session, names)
    result = {'label': label, 'taken_at': iso(taken), 'session': session, 'markers': names,
              'session_read': reading,
              'archive': file_view(archive, names) if archive else {'path': None, 'exists': False},
              'transcript': file_view(Path(transcript), names)}
    Path(out).write_text(json.dumps(result, indent=1) + '\n')
    print(f'[{label}] taken {result["taken_at"]} | session {session}')
    for kind in ('archive', 'transcript'):
        f = result[kind]
        if not f.get('exists'):
            print(f'  {kind}: MISSING ({f.get("path")})')
            continue
        print(f'  {kind}: {f["path"]}')
        print(f'    size {f["size"]} | mtime {f["mtime"]} | inode {f["inode"]} | lines {f["lines"]} | '
              f'head4096 {f["head4096_sha256"]} | line1 {f["line1_bytes"]} B | last record time {f["last_record_time"]}')
        for marker, hits in f['markers'].items():
            shown = '; '.join(f'line {h["line"]} offset {h["offset"]} time {h["time"] or "-"} type {h["type"]}'
                              f'{" (metadata line)" if h["metadata_line"] else ""}' for h in hits[:6])
            print(f'    marker {marker}: {"PRESENT " + str(len(hits)) + " line(s): " + shown if hits else "ABSENT"}')
    r = result['session_read']
    if 'error' in r:
        print(f'  session_read path: {r["error"]}')
    else:
        print(f'  session_read path (find_session + read_events): archive {r["archive_id"]} revision {r["revision"]} '
              f'events {r["events"]}')
        for marker in names:
            for content in ('text', 'all'):
                v = r.get(f'{marker}/{content}')
                print(f'    search {marker} content {content}: ' + (json.dumps(v) if isinstance(v, str) else
                      f'hits {v["hits"]} last {v["last_hit"]}'))
    print(f'  written: {out}')
    return 0


def compare(first: str, second: str) -> int:
    a, b = json.loads(Path(first).read_text()), json.loads(Path(second).read_text())
    print(f'compare {a["label"]} ({a["taken_at"]}) -> {b["label"]} ({b["taken_at"]})')
    marker = a['markers'][0]
    facts = {}
    for kind in ('archive', 'transcript'):
        x, y = a[kind], b[kind]
        if not (x.get('exists') and y.get('exists')):
            print(f'  {kind}: cannot compare (missing in one observation)'); facts[kind] = None; continue
        same_inode = x['inode'] == y['inode']
        shrank = y['size'] < x['size']
        head_same = x['head4096_sha256'] == y['head4096_sha256']
        if x['head_len'] < 4096:
            # The earlier file was shorter than 4096 bytes: compare its whole content with the same bytes now
            # (compare runs right after the later observation).
            with open(y['path'], 'rb') as handle:
                head_same = hashlib.sha256(handle.read(x['head_len'])).hexdigest()[:16] == x['head4096_sha256']
        grow1 = y['line1_bytes'] - x['line1_bytes']
        print(f'  {kind}: inode {"same" if same_inode else "CHANGED (file replaced)"} | size {x["size"]} -> {y["size"]}'
              f'{" SHRANK" if shrank else ""} | first {x["head_len"]} bytes {"same" if head_same else "CHANGED"} | '
              f'line 1 {x["line1_bytes"]} -> {y["line1_bytes"]} B ({grow1:+d})')
        xs = [h for h in x['markers'].get(marker, []) if not h['metadata_line']]
        ys = [h for h in y['markers'].get(marker, []) if not h['metadata_line']]
        shift = None
        if xs and ys:
            shift = ys[0]['offset'] - xs[0]['offset']
            print(f'    {marker} first record line: line {xs[0]["line"]} -> {ys[0]["line"]}, offset {xs[0]["offset"]} -> '
                  f'{ys[0]["offset"]} (shift {shift:+d}); beyond {a["label"]}\'s size {x["size"]} at {b["label"]}: '
                  f'{"YES (a byte split at the earlier size would count it as new)" if ys[-1]["offset"] >= x["size"] else "no"}')
        else:
            print(f'    {marker} record lines: {a["label"]} {len(xs)}, {b["label"]} {len(ys)}')
        facts[kind] = {'same_inode': same_inode, 'shrank': shrank, 'head_same': head_same, 'grow1': grow1,
                       'shift': shift, 'had': bool(xs), 'has': bool(ys)}
    arc, tr = facts.get('archive'), facts.get('transcript')
    ra = a['session_read'].get(f'{marker}/text') if 'error' not in a['session_read'] else None
    print('verdicts (observation):')
    if arc:
        latency = not arc['had'] and arc['has']
        print(f'  H1 archive lacks the last turn at {a["label"]} and has it at {b["label"]}: {"YES" if latency else "NO"}'
              f' (archive marker lines {a["label"]} {"present" if arc["had"] else "absent"}, {b["label"]} '
              f'{"present" if arc["has"] else "absent"}; session_read at {a["label"]}: '
              f'{ra["hits"] if isinstance(ra, dict) else ra} hit(s))')
        rewrite = not arc['same_inode'] or not arc['head_same'] or arc['shrank']
        print(f'  H2 archive rewritten between them: {"YES" if rewrite else "NO"}; marker shift '
              f'{arc["shift"] if arc["shift"] is not None else "n/a"} vs line-1 growth {arc["grow1"]:+d}'
              f'{" (equal: the whole shift is the metadata line)" if arc["shift"] == arc["grow1"] else ""}')
    if tr:
        rewrite = not tr['same_inode'] or not tr['head_same'] or tr['shrank']
        print(f'  H3 Claude transcript rewritten between them: {"YES" if rewrite else "NO (append only)"}; '
              f'marker shift {tr["shift"] if tr["shift"] is not None else "n/a"}')
    return 0


def sim(directory: str, phase: str, marker: str = '') -> int:
    """Rehearsal: real graftling collection over a synthetic two-turn transcript (no model, no process)."""
    from graftling.sessions.archive import SessionArchive
    from graftling.sessions.claude import ClaudeJsonlCollector

    base = Path(directory)
    base.mkdir(parents=True, exist_ok=True)
    native = base / 'native.jsonl'

    def entry(uid, parent, role, text, msg_id):
        return {'type': role, 'uuid': uid, 'parentUuid': parent, 'sessionId': 's',
                'timestamp': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z',
                'message': {'role': role, 'id': msg_id, 'model': 'native-model',
                            'content': [{'type': 'text', 'text': text}]}}

    def turn(collector, prompt_uid, parent, prompt, answer_uid, answer, msg_id):
        stream = [{'type': 'message_start', 'message': {'id': msg_id, 'model': 'native-model'}},
                  *({'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'text_delta', 'text': answer[i:i + 7]}}
                    for i in range(0, len(answer), 7)),
                  {'type': 'message_stop'}]
        records = [entry(prompt_uid, parent, 'user', prompt, 'api-' + prompt_uid),
                   entry(answer_uid, prompt_uid, 'assistant', answer, msg_id)]
        with native.open('a') as handle:
            handle.write(json.dumps(records[0]) + '\n')
        start = collector.position if hasattr(collector, 'position') else 0
        for index, event in enumerate(stream):
            collector.accept_batch([({'type': 'stream_event', 'event': event, 'session_id': 's'}, start + index + 1)])
        with native.open('a') as handle:
            handle.write(json.dumps(records[1]) + '\n')
        collector.accept_batch([({**records[1], 'session_id': 's'}, start + len(stream) + 1)])
        collector.close()

    archive = SessionArchive(base / 'swarm', save_normalized_sessions=True, backfill_history=True)
    if phase == 'first':
        native.write_text('')
        first = ClaudeJsonlCollector(archive, 's', base, 'first', resumed=False)
        first.bind(native, set())
        turn(first, 'u1', None, 'probe turn 1', 'a1', f'Turn one done: {marker or "SIM519-M1"} (the last turn before standby).',
             'api-a1')
        print('sim turn 1 (M1) collected and closed; native session s')
    else:
        later = ClaudeJsonlCollector(archive, 's', base, 'later', resumed=True)
        later.bind(native, set(), native.stat().st_size)
        turn(later, 'u2', 'a1', 'probe turn 2', 'a2', f'Turn two done: {marker or "SIM519-M2"} after the resume, with more streamed '
             'text so the draft observation kept in the metadata line is visibly larger.', 'api-a2')
        print('sim turn 2 (M2, resumed) collected and closed')
    return 0


def member(root: str) -> int:
    """Print '<agent> <name> <session>' for each Claude agent record under <swarm root>/control/agents, oldest first."""
    records = []
    for path in Path(root, 'control', 'agents').glob('*.json'):
        try:
            record = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if record.get('runtime') == 'claude':
            session = record.get('session') or (record.get('sessions') or [None])[-1]
            records.append((path.stat().st_mtime, record.get('agent') or path.stem, record.get('name'), session))
    for _, agent, name, session in sorted(records):
        print(agent, name, session)
    return 0 if records else 1


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else ''
    if mode == 'member' and len(sys.argv) == 3:
        return member(sys.argv[2])
    if mode == 'snap' and len(sys.argv) == 8:
        return snap(*sys.argv[2:8])
    if mode == 'compare' and len(sys.argv) == 4:
        return compare(sys.argv[2], sys.argv[3])
    if mode == 'sim' and len(sys.argv) in (4, 5) and sys.argv[3] in ('first', 'resume'):
        return sim(*sys.argv[2:5])
    print(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main())
