// Decode DSH Session logs and list agents notice relay messages (the reader of scripts/realhost-383/recheck-a.sh, which ran for real).
import { readFileSync, readdirSync, statSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import zlib from 'node:zlib';

const [root, output] = process.argv.slice(2);
const zstd = typeof zlib.zstdDecompressSync === 'function';
console.log(`node ${process.version}: zlib zstd ${zstd ? 'available' : 'UNAVAILABLE'}`);
const files = [];
const visit = directory => {
  for (const name of readdirSync(directory).sort()) {
    const path = join(directory, name);
    if (statSync(path).isDirectory()) visit(path);
    else if (name.endsWith('.jsonl') || name.endsWith('.jsonl.zstd')) files.push(path);
  }
};
visit(root);

/**
 * Decode every zstd frame of one appended log. zstdDecompressSync stops after
 * the first frame, so continue from the bytes it consumed; skippable frames
 * (magic 0x184D2A50-5F) are passed over by their declared size.
 */
function decodeZstd(raw) {
  const parts = [];
  let offset = 0;
  while (offset < raw.length) {
    const rest = raw.subarray(offset);
    if (rest.length >= 8 && (rest.readUInt32LE(0) & 0xfffffff0) === 0x184d2a50) {
      offset += 8 + rest.readUInt32LE(4);
      continue;
    }
    const { buffer, engine } = zlib.zstdDecompressSync(rest, { info: true });
    if (!engine.bytesWritten) throw new Error(`no progress at byte ${offset}`);
    parts.push(buffer);
    offset += engine.bytesWritten;
  }
  return Buffer.concat(parts).toString('utf8');
}

/** Yield each object carrying an agents notice relay source, with its event's type and seq. */
function* relays(value, event = {}) {
  if (Array.isArray(value)) { for (const item of value) yield* relays(item, event); return; }
  if (!value || typeof value !== 'object') return;
  const here = { type: typeof value.type === 'string' && value.type.includes('/') ? value.type : event.type,
                 seq: value.seq ?? event.seq };
  const id = value.source?.communicationId;
  if (typeof id === 'string' && id.startsWith('agents-notice:')) {
    yield { ...here, communicationId: id, kind: value.source.kind,
            text: (value.content || []).map(part => part?.text || '').join('') };
    return;
  }
  for (const item of Object.values(value)) yield* relays(item, here);
}

const found = [];
for (const path of files) {
  let text;
  try {
    const raw = readFileSync(path);
    text = path.endsWith('.zstd') ? (zstd ? decodeZstd(raw) : null)
                                  : raw.toString('utf8');
  } catch (error) {
    console.log(`DECODE FAILED ${path}: ${error.message}`);
    continue;
  }
  if (text === null) { console.log(`NOT DECODED (no zstd in this Node) ${path}`); continue; }
  const lines = text.split('\n');
  console.log(`decoded ${path}: ${lines.filter(Boolean).length} lines`);
  lines.forEach((line, index) => {
    let record;
    try { record = JSON.parse(line); } catch { return; }
    for (const relay of relays(record)) found.push({ log: path, line: index + 1, ...relay });
  });
}
writeFileSync(output, found.map(item => JSON.stringify(item)).join('\n') + (found.length ? '\n' : ''));
for (const item of found) {
  console.log(`relay ${item.log}:${item.line} ${item.type} seq=${item.seq} ${item.communicationId} ` +
              JSON.stringify(item.text.slice(0, 160)));
}
console.log(`relay messages found: ${found.length}`);
