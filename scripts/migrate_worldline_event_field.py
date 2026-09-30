#!/usr/bin/env python3
"""One-time migration: rename the Worldline event ``kind`` key to ``event``.

Usage::

    python scripts/migrate_worldline_event_field.py <worldline-directory>

``<worldline-directory>`` is the directory that holds one project Worldline's
``NNNN.jsonl`` shards. Each shard holds one JSON record per line.

The script renames only each record's top-level ``kind`` key, leaving the
event type value, timestamps, causality, evidence and payload content
unchanged. A ``kind`` key nested inside a payload is never touched. Records
that already carry ``event`` are left as they are, so repeated runs change
nothing; a record that carries both keys is refused rather than guessed at.
Every shard is validated before any file is written, and each written shard is
replaced atomically.
"""

from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
from pathlib import Path


def _migrate_record(raw_line: str, path: Path, number: int) -> tuple[dict, bool]:
    """Return one record with its top-level key migrated, and whether it changed."""

    try:
        record = json.loads(raw_line)
    except ValueError as error:
        raise ValueError("{0}:{1} is not valid JSON".format(path, number)) from error
    if not isinstance(record, dict):
        raise ValueError("{0}:{1} is not a JSON object".format(path, number))

    carries_kind = "kind" in record
    carries_event = "event" in record
    if carries_kind and carries_event:
        raise ValueError(
            "{0}:{1} carries both kind and event; refusing to change it".format(
                path, number
            )
        )
    if not carries_kind and not carries_event:
        raise ValueError(
            "{0}:{1} carries neither kind nor event".format(path, number)
        )
    if not carries_kind:
        return record, False

    # Rebuild the mapping in order so ``event`` keeps the replaced key's position.
    migrated = {
        "event" if key == "kind" else key: value for key, value in record.items()
    }
    return migrated, True


def _migrate_shard(path: Path) -> tuple[list[dict], int]:
    """Migrate one shard in memory and report how many records changed."""

    records: list[dict] = []
    changed = 0
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        record, record_changed = _migrate_record(line, path, number)
        records.append(record)
        changed += int(record_changed)
    return records, changed


def _write_atomically(path: Path, records: list[dict]) -> None:
    """Replace one shard with its canonical compact serialization."""

    content = "".join(
        json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
        for record in records
    )
    descriptor, temporary_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=path.name + ".", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary_name, stat.S_IMODE(path.stat().st_mode))
        os.replace(temporary_name, path)
        try:
            directory = os.open(str(path.parent), os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        except OSError:
            # Directory fsync is not available on every platform; the renamed
            # shard itself is already durable.
            pass
    except BaseException:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise


def main(argv: list[str]) -> int:
    """Migrate every shard under the selected Worldline directory."""

    if len(argv) != 2:
        print(
            "usage: migrate_worldline_event_field.py <worldline-directory>",
            file=sys.stderr,
        )
        return 2
    directory = Path(argv[1])
    if not directory.is_dir():
        print("{0} is not a directory".format(directory), file=sys.stderr)
        return 2
    shards = sorted(directory.glob("*.jsonl"))
    migrated: list[tuple[Path, list[dict]]] = []
    try:
        for shard in shards:
            records, changed = _migrate_shard(shard)
            if changed:
                migrated.append((shard, records))
    except ValueError as error:
        print("migration refused: {0}".format(error), file=sys.stderr)
        return 1

    for shard, records in migrated:
        _write_atomically(shard, records)
    print(
        "migrated {0} of {1} shards under {2}".format(
            len(migrated), len(shards), directory
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
