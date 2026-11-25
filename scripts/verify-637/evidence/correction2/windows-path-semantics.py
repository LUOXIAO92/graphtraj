"""Emulate, on any host, how the product's check (codex/app_server.py: Path(path).is_absolute()) judges the peer's
reported rollout path on Windows, before and after correction 2. On Windows os.path.abspath(p) is GetFullPathNameW,
which prefixes the current drive to a rooted path; here that is ntpath.join(<drive of the runner's cwd>, p)."""
import ntpath
import os
import posixpath
from pathlib import PurePosixPath, PureWindowsPath

thread = 'thread-1'
before = '/native/' + thread + '.jsonl'
runner_cwd = r'D:\a\graftling\graftling'  # the checkout directory in run 45653900507's logs
after_windows = ntpath.normpath(ntpath.join(PureWindowsPath(runner_cwd).drive + '\\', before.lstrip('/')))
print('before, Windows:', repr(before), 'is_absolute =', PureWindowsPath(before).is_absolute())
print('after,  Windows:', repr(after_windows), 'is_absolute =', PureWindowsPath(after_windows).is_absolute())
print('after,  POSIX  :', repr(posixpath.abspath(before)), 'unchanged =', posixpath.abspath(before) == before,
      'is_absolute =', PurePosixPath(posixpath.abspath(before)).is_absolute())
print('this host os.path.abspath:', repr(os.path.abspath(before)))
