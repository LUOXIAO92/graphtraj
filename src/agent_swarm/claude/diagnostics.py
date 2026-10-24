"""Bounded nonsecret projections of actual Claude launch and native metadata."""
from __future__ import annotations

import json
import re

from .support import redact


MODES = ('default', 'manual', 'auto', 'acceptEdits', 'plan', 'dontAsk', 'bypassPermissions')


def native_projection(record: object) -> dict:
    """Copy only typed capability/mode/status fields, never arbitrary native text."""
    result = {'reason': 'unknown'}
    if not isinstance(record, dict):
        record = {}
    if record.get('reason') in ('disabled_by_settings', 'unsupported_model', 'server_disabled', 'account_disabled'):
        result['reason'] = record['reason']
    for key in ('hooks_applied', 'autoModeAvailable', 'supportsAutoMode', 'auto_mode_available'):
        result[key] = record[key] if type(record.get(key)) is bool else 'unknown'
    for key in ('permissionMode', 'permission_mode'):
        result[key] = record[key] if record.get(key) in MODES else 'unknown'
    for key in ('subtype', 'status'):
        result[key] = record[key] if record.get(key) in ('success', 'error', 'ready', 'unavailable') else 'unknown'
    return result


def model_projection(value: object) -> str:
    """Expose a bounded model identifier, rejecting arbitrary native prose."""
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9._:/-]{1,100}', value):
        return 'unknown'
    return redact(value)


def launch_projection(argv: list[str]) -> dict:
    """Project the same argv object passed to Popen, without paths or prompt text."""
    def option(name: str) -> str | None:
        """Read one requested CLI value, retaining omission as None."""
        return argv[argv.index(name) + 1] if name in argv else None

    settings = json.loads(option('--settings') or '{}')
    permissions = settings.get('permissions', {})
    sandbox = settings.get('sandbox', {})
    mode = option('--permission-mode')
    inline = permissions.get('defaultMode')
    effort = option('--effort')
    return {
        'permission_mode': mode if mode in MODES or mode is None else 'unknown',
        'inline_default_mode': inline if inline in MODES or inline is None else 'unknown',
        'model': model_projection(option('--model')),
        'effort': effort if effort in ('low', 'medium', 'high', 'xhigh', 'max') else 'unknown',
        'restricted': '--restricted' in argv,
        'strict_mcp': '--strict-mcp-config' in argv,
        'stdio_permission_handler': option('--permission-prompt-tool') == 'stdio',
        'block_reads_outside_working_directories': permissions.get('blockReadsOutsideWorkingDirectories') is True,
        'sandbox': {key: sandbox[key] if type(sandbox.get(key)) is bool else 'unknown'
                    for key in ('enabled', 'failIfUnavailable', 'allowUnsandboxedCommands',
                                'autoAllowBashIfSandboxed')},
    }


def warning_projection(text: object) -> list[str]:
    """Reduce recognized native warnings to fixed labels; discard all free text."""
    if not isinstance(text, str):
        return []
    bounded = redact(text[:4096]).lower()
    if ('permission mode forced to default' in bounded
            and 'claude_code_subprocess_env_scrub' in bounded):
        return ['native_permission_forced_default_by_environment_scrub']
    if not re.search(r'auto[- ]mode|classifier', bounded):
        return []
    labels = []
    for word, label in (
        ('disabled', 'native_auto_disabled'), ('unavailable', 'native_auto_unavailable'),
        ('fallback', 'native_auto_fallback'), ('cannot determine the safety', 'native_classifier_failed'),
    ):
        if word in bounded:
            labels.append(label)
    return labels
