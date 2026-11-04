"""Dry check: every literal call('<feature>', ...) in the 394 scripts against the agents schemas of this checkout.

Usage: PYTHONPATH=<worktree>/src python check_calls.py <file> ...
Prints one line per call site: OK, or what the schema refuses. A call built with **arguments is listed as such.
"""
import ast
import sys

from graftling.discovery import feature_schema


def main() -> int:
    """Check each file; exit 1 if any call site is refused."""
    bad = 0
    for name in sys.argv[1:]:
        tree = ast.parse(open(name).read())
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and getattr(node.func, 'id', None) == 'call' and node.args
                    and isinstance(node.args[0], ast.Constant)):
                continue
            feature = node.args[0].value
            where = f'{name.rsplit("/", 1)[-1]}:{node.lineno} {feature}'
            try:
                schema = feature_schema(feature)
            except Exception as error:
                print(f'REFUSED {where}: no such feature ({error})')
                bad += 1
                continue
            given = {keyword.arg for keyword in node.keywords if keyword.arg}
            spread = any(keyword.arg is None for keyword in node.keywords)
            allowed = set(schema.get('properties', {}))
            unknown = sorted(given - allowed) if schema.get('additionalProperties') is False else []
            missing = [] if spread else sorted(set(schema.get('required', [])) - given)
            if unknown or missing:
                print(f'REFUSED {where}: unexpected {unknown}, missing {missing}')
                bad += 1
            else:
                print(f'OK {where}: {sorted(given)}' + (' plus **arguments (checked where built)' if spread else ''))
    return 1 if bad else 0


if __name__ == '__main__':
    raise SystemExit(main())
