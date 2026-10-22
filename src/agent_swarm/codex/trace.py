"""Retain a link to an owned native rollout, optionally collecting its records."""
from __future__ import annotations
import os
from pathlib import Path
from typing import Any, Optional
class CodexNativeTrace:
    """Read one Runtime-owned native Session record through its retained Trace.

    The Trace entry is a symbolic link to the native rollout file that the
    Runtime owns, so a reader sees the native records themselves, including
    records appended while the Session runs. An assigned archive additionally
    commits those records into project storage. GraphTraj never writes through
    the native link.
    """

    def __init__(
        self,
        trace_file: Path,
        session: str,
        rollout_path: Path | None,
        codex_home: Path,
        *,
        archive: Any | None = None,
    ) -> None:
        """Record the Trace entry and the native Session it must read."""

        self._trace_file = trace_file
        self._session = session
        self._codex_home = codex_home
        self._rollout = rollout_path
        self._archive = archive
        self._collected_file: tuple | None = None

    def collect(self) -> None:
        """Archive new records and link the Trace when the native file exists."""

        if self._rollout is None:
            discovered = _find_native_session(self._session, self._codex_home)
            if discovered is None:
                return
            self._rollout = discovered
        try:
            stat = self._rollout.stat()
        except FileNotFoundError:
            # A notification can precede creation of the declared rollout.
            return
        signature = (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)
        if hasattr(self._archive, 'collection_key'):
            signature += (self._archive.collection_key(),)
        if self._archive is not None and signature != self._collected_file:
            self._archive.collect(self._rollout)
            # Capture the pre-read signature: appends during collection must
            # trigger another pass, including completion of a partial line.
            self._collected_file = signature
        if _linked_to(self._trace_file, self._rollout):
            return
        if _retains_records(self._trace_file):
            return
        _link_native_trace(self._trace_file, self._rollout)


def _linked_to(trace_file: Path, rollout: Path) -> bool:
    """Return whether this Trace entry already reads that native file."""

    try:
        if not trace_file.is_symlink():
            return False
        return Path(os.path.realpath(trace_file)) == Path(os.path.realpath(rollout))
    except OSError:
        return False


def _retains_records(trace_file: Path) -> bool:
    """Return whether this Trace entry already holds an earlier record set."""

    try:
        return not trace_file.is_symlink() and trace_file.stat().st_size > 0
    except OSError:
        return False


def _link_native_trace(trace_file: Path, rollout: Path) -> None:
    """Point one Trace entry at its Runtime-owned native Session file.

    The link replaces any placeholder atomically so a reader never observes a
    missing Trace entry.
    """

    trace_file.parent.mkdir(parents=True, exist_ok=True)
    pending = trace_file.with_name("." + trace_file.name + ".link")
    pending.unlink(missing_ok=True)
    pending.symlink_to(rollout)
    os.replace(pending, trace_file)


def _find_native_session(
    session: str,
    codex_home: Path | None = None,
) -> Optional[Path]:
    if codex_home is None:
        codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    sessions = codex_home / "sessions"
    try:
        return next(sessions.rglob("*{0}.jsonl".format(session)), None)
    except OSError:
        return None

