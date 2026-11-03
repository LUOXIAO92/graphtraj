"""Dry check: calls from the 392 step code into its own helper modules, against their current signatures.

Usage: python check_helpers.py <file> ...
Reads only source, never imports it. For each call to a top-level function of scratch_project, rh392,
residual, checks or child_env, reached as `alias.func(...)` after `import <module> as alias`, as `func(...)`
after `from <module> import func`, or as a function of the same file, it checks positional and keyword
arity. A call with *args or **kwargs is checked only as far as its fixed part goes.
"""
import ast
from pathlib import Path
import sys

HELPERS = ('scratch_project', 'rh392', 'residual', 'checks', 'child_env')


def signatures(path: Path) -> dict[str, ast.arguments]:
    """Return the top-level functions of one module by name."""
    tree = ast.parse(path.read_text())
    return {node.name: node.args for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}


def problem(arguments: ast.arguments, call: ast.Call) -> str | None:
    """Say what is wrong with one call against one signature, or None."""
    positional = [*arguments.posonlyargs, *arguments.args]
    names = [item.arg for item in positional]
    keyword_only = [item.arg for item in arguments.kwonlyargs]
    required = names[:len(names) - len(arguments.defaults)]
    required_keyword = [name for name, default in zip(keyword_only, arguments.kw_defaults) if default is None]
    starred = any(isinstance(item, ast.Starred) for item in call.args)
    spread = any(keyword.arg is None for keyword in call.keywords)
    given = [] if starred else names[:len(call.args)]
    if not starred and len(call.args) > len(names) and arguments.vararg is None:
        return f'{len(call.args)} positional arguments, at most {len(names)}'
    by_keyword = [keyword.arg for keyword in call.keywords if keyword.arg]
    for name in by_keyword:
        if name not in names and name not in keyword_only and arguments.kwarg is None:
            return f'unexpected keyword {name!r}'
        if name in given:
            return f'{name!r} given twice'
    if not (starred or spread):
        missing = [name for name in required if name not in given and name not in by_keyword]
        missing += [name for name in required_keyword if name not in by_keyword]
        if missing:
            return f'missing {missing}'
    return None


def main() -> int:
    """Check each file; exit 1 if any call is wrong."""
    directory = Path(__file__).resolve().parent.parent
    modules = {name: signatures(directory / f'{name}.py') for name in HELPERS}
    bad = checked = 0
    for name in sys.argv[1:]:
        path = Path(name)
        tree = ast.parse(path.read_text())
        aliases, direct = {}, dict.fromkeys(signatures(path), path.stem)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for item in node.names:
                    if item.name in modules:
                        aliases[item.asname or item.name] = item.name
            elif isinstance(node, ast.ImportFrom) and node.module in modules:
                for item in node.names:
                    direct[item.asname or item.name] = node.module
        own = signatures(path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            target = None
            if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and node.func.value.id in aliases:
                module = aliases[node.func.value.id]
                target = (module, node.func.attr, modules[module].get(node.func.attr))
            elif isinstance(node.func, ast.Name) and node.func.id in direct:
                module = direct[node.func.id]
                table = own if module == path.stem else modules.get(module, {})
                target = (module, node.func.id, table.get(node.func.id))
            if target is None or target[2] is None:
                continue
            checked += 1
            said = problem(target[2], node)
            if said:
                bad += 1
                print(f'WRONG {path.name}:{node.lineno} {target[0]}.{target[1]}: {said}')
    print(f'{checked} helper calls checked, {bad} wrong')
    return 1 if bad else 0


if __name__ == '__main__':
    raise SystemExit(main())
