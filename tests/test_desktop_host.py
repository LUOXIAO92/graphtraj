"""Bounded GUI proof checks; actual packaged-host acceptance remains a desktop check."""
import hashlib
import json
import os
from pathlib import Path

import pytest

from graphtraj.interfaces import desktop_host as host


def test_window_proof_is_release_bound_project_scoped_and_keeps_agent_limits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An owned pipe alone, changed code, other projects or Agent context cannot grant access."""
    exe = tmp_path / 'GraphTraj'
    main = tmp_path / 'resources/app/dist-electron/main.js'
    main.parent.mkdir(parents=True)
    exe.write_bytes(b'controlled executable')
    main.write_bytes(b'controlled GUI bridge')
    release = {'executable': exe.name, 'files': {
        str(p.relative_to(tmp_path)): hashlib.sha256(p.read_bytes()).hexdigest() for p in (exe, main)
    }}
    (tmp_path / 'desktop-host.json').write_text(json.dumps(release))
    monkeypatch.setattr(host, '__file__', str(tmp_path / 'desktop_host.py'))
    monkeypatch.setattr(host, '_executable', lambda pid: exe)
    monkeypatch.setattr(host, 'discover_runner_directory', lambda cwd: tmp_path)
    monkeypatch.setattr(host, 'runtime_caller_is_bound', lambda: False)
    monkeypatch.setattr(host, 'caller_runtime', lambda: None)
    monkeypatch.setattr(host, 'process_caller_alias', lambda runner, pid: None)
    # These locators are retained; only positive kernel/package/pipe proof changes the surface.
    monkeypatch.setenv('CODEX_THREAD_ID', 'retained-controlled-locator')
    read_fd, write_fd = os.pipe()
    with os.fdopen(read_fd) as reader, os.fdopen(write_fd, 'w') as writer:
        with host.window_pipe(tmp_path, reader, writer):
            assert host.owns_project(tmp_path)
            assert not host.owns_project(tmp_path / 'other')
        assert not host.owns_project(tmp_path)
        monkeypatch.setattr(host, 'runtime_caller_is_bound', lambda: True)
        with host.window_pipe(tmp_path, reader, writer):
            assert not host.owns_project(tmp_path)
        monkeypatch.setattr(host, 'runtime_caller_is_bound', lambda: False)
        monkeypatch.setattr(host, 'process_caller_alias', lambda runner, pid: 'real-agent')
        with host.window_pipe(tmp_path, reader, writer):
            assert not host.owns_project(tmp_path)
        monkeypatch.setattr(host, 'process_caller_alias', lambda runner, pid: None)
        main.write_bytes(b'modified GUI bridge')
        with host.window_pipe(tmp_path, reader, writer):
            assert not host.owns_project(tmp_path)
        (tmp_path / 'desktop-host.json').unlink()
        with host.window_pipe(tmp_path, reader, writer):
            assert not host.owns_project(tmp_path)
    assert os.environ['CODEX_THREAD_ID'] == 'retained-controlled-locator'
