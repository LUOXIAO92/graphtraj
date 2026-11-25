"""List text-mode I/O calls in a source tree that pass no encoding= (static, AST)."""
import ast, sys
from pathlib import Path
root = Path(sys.argv[1])
def kw(call, name):
    return next((k.value for k in call.keywords if k.arg == name), None)
def const(node):
    return node.value if isinstance(node, ast.Constant) else None
for path in sorted(root.rglob('*.py')):
    tree = ast.parse(path.read_text(encoding='utf-8'))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or kw(node, 'encoding') is not None:
            continue
        f = node.func
        name = f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else None
        mode = None
        if name in ('read_text', 'write_text'):
            pass
        elif name in ('open', 'fdopen', 'NamedTemporaryFile', 'TemporaryFile', 'SpooledTemporaryFile'):
            if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == 'os' and name == 'open':
                continue
            m = kw(node, 'mode')
            args = node.args
            if m is None:
                # positional mode: open(path, mode) / Path.open(mode) / fdopen(fd, mode)
                if name == 'open' and isinstance(f, ast.Attribute):
                    m = args[0] if args else None
                elif name in ('open', 'fdopen'):
                    m = args[1] if len(args) > 1 else None
            mode = const(m) if m is not None else ('r' if name in ('open', 'fdopen') else 'w+b')
            if not isinstance(mode, str) or 'b' in mode:
                continue
            # skip urllib opener.open(request) / websocket.open()
            if name == 'open' and isinstance(f, ast.Attribute) and (not args or not isinstance(const(args[0]) if args else None, str)) and m is None and args:
                if not (isinstance(args[0], ast.Constant) and isinstance(args[0].value, str)):
                    continue
        elif name in ('Popen', 'run', 'check_output', 'check_call', 'call'):
            t = kw(node, 'text'); u = kw(node, 'universal_newlines')
            if not ((t is not None and const(t) is not False) or (u is not None and const(u) is not False)):
                continue
        elif name == 'TextIOWrapper':
            pass
        else:
            continue
        print(f'{path.relative_to(root)}:{node.lineno}: {name} {ast.unparse(node)[:110]}')
