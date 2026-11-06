"""A connection service whose control directory is removed stops once (450)."""
from pathlib import Path
import shutil
import threading
import time

from graftling.connection import worker_connection


def serving_threads() -> list[threading.Thread]:
    return [thread for thread in threading.enumerate()
            if getattr(getattr(thread, '_target', None), '__name__', None) == 'serve']


def test_removed_control_directory_stops_the_service(tmp_path: Path, capfd) -> None:
    before = set(serving_threads())
    with worker_connection(tmp_path, lambda request: {}) as address:
        server = (set(serving_threads()) - before).pop()
        shutil.rmtree(address)
        server.join(timeout=5)
        assert not server.is_alive()
    err = capfd.readouterr().err
    assert err.count('no longer exists; its connection service stopped.') == 1
    assert address in err and 'FileNotFoundError' not in err
