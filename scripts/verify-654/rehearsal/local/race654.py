"""Throwaway pytest plugin (654, never committed to graftling): delay the Pi host's settle thread.

Load with -p race654 (PYTHONPATH pointing here). Wraps AgentControl.settle_notice so a call made on a
thread other than the main thread sleeps RACE654_DELAY seconds (default 0.3) before settling, which stands
for a slow runner scheduling the daemon thread that PiNotices.acknowledge starts.
"""
import os
import threading
import time

from graftling.control import AgentControl

_original = AgentControl.settle_notice
DELAY = float(os.environ.get('RACE654_DELAY', '0.3'))


def _delayed(self, *args, **kwargs):
    if threading.current_thread() is not threading.main_thread():
        time.sleep(DELAY)
    return _original(self, *args, **kwargs)


AgentControl.settle_notice = _delayed


def pytest_report_header(config):
    return f'race654: AgentControl.settle_notice delayed {DELAY}s off the main thread'
