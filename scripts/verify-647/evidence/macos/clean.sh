#!/bin/sh
# Run a command with a minimal environment: no provider credentials, TMPDIR outside the Harness.
exec env -i HOME="$HOME" USER="$USER" PATH=/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:/usr/local/bin TMPDIR="${TMPDIR:-/tmp}" LANG=en_US.UTF-8 "$@"
