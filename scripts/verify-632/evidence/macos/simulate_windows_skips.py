"""Rehearsal-only pytest plugin (632): make tests/posix_only.py act as on Windows, on this POSIX host.

Shows which tests the POSIX-only marks skip on Windows and with which reasons. Platform checks other
than posix_only.WINDOWS (for example test_codex_tool_reclaim_462's sys.platform skipif) are not simulated.
"""
import posix_only


def pytest_configure(config):
    posix_only.WINDOWS = True
