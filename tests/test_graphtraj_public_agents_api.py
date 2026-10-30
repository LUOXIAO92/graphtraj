"""GraphTraj uses agents only through the names PUBLIC_API.md section 1.3 lists."""
from __future__ import annotations

import ast
import importlib
import importlib.util
import inspect
import os
from pathlib import Path
import posixpath
import re
import subprocess
import sys

import pytest

SOURCE = Path(__file__).resolve().parents[1] / 'src'
GRAPHTRAJ = SOURCE / 'graphtraj'
CONTRACT = SOURCE / 'agent_swarm' / 'PUBLIC_API.md'

ROOT = 'agent_swarm'
RUNTIME_PACKAGES = ('agent_swarm.claude', 'agent_swarm.codex', 'agent_swarm.pi', 'agent_swarm.dsh')
PACKAGES = (ROOT, *RUNTIME_PACKAGES, 'agent_swarm.sessions')


def published() -> dict[str, set[str]]:
    """Read each public package's real ``__all__``; a package without one publishes nothing."""
    return {package: set(getattr(importlib.import_module(package), '__all__', ())) for package in PACKAGES}


def agents_module(name: object) -> bool:
    """Whether a dotted import target belongs to the agents package."""
    return isinstance(name, str) and (name == ROOT or name.startswith(ROOT + '.'))


def private(name: str) -> bool:
    """Whether a member name is underscore-private, not a dunder such as ``__init__``."""
    return name.startswith('_') and not name.endswith('__')


def import_findings(tree: ast.AST, names: dict[str, set[str]]) -> list[str]:
    """Report every import of an unpublished module or name, at any scope.

    ``names`` is :func:`published`'s result. A package named by an import is
    public only when it is one of ``PACKAGES``; attributes reached through a
    plain ``import agent_swarm`` are checked like imported names.
    """
    findings = []
    # Local names bound to a public package, with the package they name.
    bound = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if not agents_module(alias.name):
                    continue
                if alias.name not in names:
                    findings.append(f'line {node.lineno}: imports internal module {alias.name}')
                elif alias.asname:
                    bound[alias.asname] = alias.name
                else:
                    bound[ROOT] = ROOT
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and agents_module(node.module):
            if node.module not in names:
                findings.append(f'line {node.lineno}: imports internal module {node.module}')
                continue
            for alias in node.names:
                if alias.name == '*' or alias.name in names[node.module]:
                    continue
                if f'{node.module}.{alias.name}' in names:
                    bound[alias.asname or alias.name] = f'{node.module}.{alias.name}'
                    continue
                findings.append(f'line {node.lineno}: imports unpublished name {node.module}.{alias.name}')
        elif (isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant)
              and agents_module(node.args[0].value)
              and (isinstance(node.func, ast.Name) and node.func.id in {'__import__', 'import_module'}
                   or isinstance(node.func, ast.Attribute) and node.func.attr == 'import_module')
              and node.args[0].value not in names):
            findings.append(f'line {node.lineno}: imports internal module {node.args[0].value} dynamically')

    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in bound:
            package = bound[node.value.id]
            target = f'{package}.{node.attr}'
            if node.attr not in names[package] and target not in names:
                findings.append(f'line {node.lineno}: uses unpublished name {target}')
    return findings


def agents_private_members(cls: type) -> set[str]:
    """Return the underscore members an agents class and its agents bases define.

    Instance attributes count too, so they are read from each class's source.
    """
    members = set()
    for base in cls.__mro__:
        if not agents_module(base.__module__):
            continue
        members |= {name for name in vars(base) if private(name)}
        members |= {node.attr for node in ast.walk(ast.parse(inspect.getsource(base)))
                    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                    and node.value.id == 'self' and private(node.attr)}
    return members


def imported_classes(tree: ast.AST) -> dict[str, tuple[str, str]]:
    """Map local names to their ``(module, name)`` for every absolute from-import."""
    return {alias.asname or alias.name: (node.module, alias.name)
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module
            for alias in node.names}


def agents_bases(module: str, name: str, trees: dict[str, ast.AST]) -> list[type]:
    """Follow one class name through GraphTraj modules to the agents classes below it.

    An unpublished base has its import reported separately and is followed
    here as well, so its private members are reported too.
    """
    if agents_module(module):
        value = getattr(importlib.import_module(module), name, None)
        return [value] if inspect.isclass(value) else []
    tree = trees.get(module)
    if tree is None:
        return []
    imports = imported_classes(tree)
    if name in imports:
        return agents_bases(*imports[name], trees)
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == name:
            for base in node.bases:
                if isinstance(base, ast.Name):
                    found += agents_bases(module, base.id, trees)
    return found


def subclass_findings(tree: ast.AST, module: str, trees: dict[str, ast.AST]) -> list[str]:
    """Report a GraphTraj class that overrides or reaches a base's underscore member."""
    findings = []
    for cls in (node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)):
        members = set()
        for base in cls.bases:
            if isinstance(base, ast.Name):
                for agents_class in agents_bases(module, base.id, trees):
                    members |= agents_private_members(agents_class)
        if not members:
            continue
        for item in cls.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name in members:
                findings.append(f'line {item.lineno}: {cls.name} overrides {item.name}')
            elif isinstance(item, ast.Assign):
                for target in item.targets:
                    if isinstance(target, ast.Name) and target.id in members:
                        findings.append(f'line {item.lineno}: {cls.name} replaces {target.id}')
        for node in ast.walk(cls):
            if not isinstance(node, ast.Attribute) or node.attr not in members:
                continue
            instance = isinstance(node.value, ast.Name) and node.value.id in {'self', 'cls'}
            parent = (isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name)
                      and node.value.func.id == 'super')
            if instance or parent:
                findings.append(f'line {node.lineno}: {cls.name} uses {node.attr}')
    return findings


def contract_section() -> str:
    """Return the text of section 1.3 of the contract."""
    text = CONTRACT.read_text(encoding='utf-8')
    return text[text.index('### 1.3'):text.index('### 1.4')]


def contract_javascript() -> dict[str, set[str]]:
    """Read the JavaScript table of section 1.3: file to its public exports."""
    table = {}
    for line in contract_section().splitlines():
        match = re.match(r'\| `(agent_swarm/[\w./-]+\.mjs)` \| (.+) \|$', line)
        if match:
            table[match[1]] = set(re.findall(r'`(\w+)`', match[2]))
    return table


MODULE_FORM = re.compile(
    r"^\s*(?:import|export)\b(?P<clause>[^;'\"]*?)\bfrom\s*['\"](?P<source>[^'\"]+)['\"]"
    r"|^\s*import\s*['\"](?P<bare>[^'\"]+)['\"]"
    r"|\bimport\(\s*['\"](?P<dynamic>[^'\"]+)['\"]\s*\)",
    re.MULTILINE,
)


def javascript_findings(path: str, source: str, table: dict[str, set[str]]) -> list[str]:
    """Report a ``.mjs`` import of an agents file or export the contract does not list.

    ``path`` is the file's location below ``src``, used to resolve relative
    imports. A whole-module, namespace or default import is not a listed
    export, so it is reported as well.
    """
    findings = []
    for match in MODULE_FORM.finditer(source):
        specifier = match['source'] or match['bare'] or match['dynamic']
        target = (posixpath.normpath(posixpath.join(posixpath.dirname(path), specifier))
                  if specifier.startswith('.') else specifier)
        if not agents_module(target.split('/')[0]):
            continue
        if target not in table:
            findings.append(f'imports unlisted file {target}')
            continue
        braces = re.fullmatch(r'\s*\{(?P<names>[^}]*)\}\s*', match['clause'] or '')
        if braces is None:
            findings.append(f'imports all of {target} instead of listed exports')
            continue
        for item in filter(None, (part.strip() for part in braces['names'].split(','))):
            name = item.split()[0]
            if name not in table[target]:
                findings.append(f'imports unlisted export {target}: {name}')
    return findings


def scan_graphtraj() -> list[str]:
    """Scan every GraphTraj source file and return all findings, each naming its file."""
    names = published()
    files = {}
    for path in sorted(GRAPHTRAJ.rglob('*.py')):
        relative = path.relative_to(SOURCE).with_suffix('')
        module = '.'.join(relative.parts[:-1] if relative.name == '__init__' else relative.parts)
        files[module] = (path, ast.parse(path.read_text(encoding='utf-8')))
    trees = {module: tree for module, (_, tree) in files.items()}

    findings = []
    for module, (path, tree) in files.items():
        for finding in import_findings(tree, names) + subclass_findings(tree, module, trees):
            findings.append(f'{path.relative_to(SOURCE)}: {finding}')
    table = contract_javascript()
    for path in sorted(GRAPHTRAJ.rglob('*.mjs')):
        relative = path.relative_to(SOURCE).as_posix()
        for finding in javascript_findings(relative, path.read_text(encoding='utf-8'), table):
            findings.append(f'{relative}: {finding}')
    return findings


def test_graphtraj_uses_only_published_agents_names() -> None:
    """Any unpublished agents import, member or JavaScript export in GraphTraj fails here."""
    findings = scan_graphtraj()

    assert not findings, f'{len(findings)} uses of unpublished agents names:\n' + '\n'.join(findings)


def test_every_public_name_is_listed_in_the_contract() -> None:
    """Each ``__all__`` name appears in section 1.3, a package's names in its own row."""
    section = contract_section()
    names = published()
    for package in PACKAGES:
        assert names[package], f'{package} has no __all__'

    listed = set(re.findall(r'`(?:agent_swarm\.)?(\w+)\b', section))
    assert not sorted(names[ROOT] - listed)
    for package in PACKAGES[1:]:
        row = next((line for line in section.splitlines() if line.startswith(f'| `{package}` |')), '')
        assert not sorted(names[package] - set(re.findall(r'`(\w+)`', row))), package


def test_no_public_name_is_private_or_a_missing_attribute() -> None:
    """A published name loads, and no underscore name is published."""
    for package, names in published().items():
        module = importlib.import_module(package)
        for name in names:
            assert name == '__version__' or not name.startswith('_'), f'{package}.{name}'
            assert hasattr(module, name), f'{package}.{name}'


def test_listed_javascript_exports_exist() -> None:
    """Every export the contract lists is really exported by its file."""
    table = contract_javascript()

    assert table
    for file, exports in table.items():
        source = (SOURCE / file).read_text(encoding='utf-8')
        for name in exports:
            assert re.search(rf'export\s+(?:async\s+)?(?:function\*?|const|let|class)\s+{name}\b', source), (file, name)


def test_importing_agents_loads_no_runtime_package() -> None:
    """``import agent_swarm`` starts no Runtime package, and the MCP entry imports once."""
    environment = {**os.environ, 'PYTHONPATH': str(SOURCE)}
    environment.pop('AGENT_SWARM_CONNECTION', None)
    code = ('import sys, agent_swarm; '
            f'print([name for name in sys.modules if name.startswith({RUNTIME_PACKAGES!r})])')
    result = subprocess.run([sys.executable, '-c', code], env=environment,
                            capture_output=True, text=True, check=True)
    assert result.stdout.strip() == '[]'

    # A name loaded early would warn that the module is found twice.
    subprocess.run([sys.executable, '-W', 'error', '-m', 'agent_swarm.mcp'], env=environment,
                   input='', text=True, check=True)


SAMPLE_NAMES = {'agent_swarm': {'Run', 'bind'}, 'agent_swarm.codex': {'CodexDriver'}}


@pytest.mark.parametrize('source', [
    'from agent_swarm.control import AgentControl',
    'from agent_swarm.control import _scope',
    'def late():\n    from agent_swarm.control import _alive',
    'import agent_swarm.control',
    'import agent_swarm.control as control',
    'from agent_swarm import _hidden',
    'from agent_swarm import internal_name',
    'from agent_swarm.codex import _private',
    'from agent_swarm.codex import app_server',
    'import agent_swarm\nagent_swarm.hidden()',
    'import agent_swarm.codex as codex\ncodex.hidden()',
    'from agent_swarm import codex\ncodex.hidden()',
    'import importlib\nimportlib.import_module("agent_swarm.control")',
    'from importlib import import_module\nimport_module("agent_swarm.sessions.dsh")',
    '__import__("agent_swarm.control")',
])
def test_import_check_reports_every_form(source: str) -> None:
    """Module-level, local, aliased, dynamic and attribute uses are all reported."""
    assert import_findings(ast.parse(source), SAMPLE_NAMES)


@pytest.mark.parametrize('source', [
    'from agent_swarm import Run, bind',
    'from agent_swarm.codex import CodexDriver as Driver',
    'import agent_swarm\nagent_swarm.bind()',
    'import agent_swarm.codex as codex\ncodex.CodexDriver()',
    'import importlib\nimportlib.import_module("agent_swarm.codex")',
    'import other_package.control',
])
def test_import_check_accepts_published_names(source: str) -> None:
    """A published name, however it is imported, is not reported."""
    assert not import_findings(ast.parse(source), SAMPLE_NAMES)


SAMPLE_BASE = """
class Base:
    _flag = True

    def __init__(self):
        self._state = 1

    def _hook(self):
        pass
"""


@pytest.fixture
def sample_base(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Register a small agents class, from a real file, as ``agent_swarm.sample``."""
    file = tmp_path / 'sample.py'
    file.write_text(SAMPLE_BASE, encoding='utf-8')
    specification = importlib.util.spec_from_file_location('agent_swarm.sample', file)
    module = importlib.util.module_from_spec(specification)
    monkeypatch.setitem(sys.modules, 'agent_swarm.sample', module)
    specification.loader.exec_module(module)


@pytest.mark.parametrize('body', [
    'def _hook(self): pass',
    'async def _hook(self): pass',
    '_flag = False',
    'def run(self): super()._hook()',
    'def run(self): self._hook()',
    'def run(self): return self._state',
    'def run(self): self._state = 2',
])
@pytest.mark.usefixtures('sample_base')
def test_subclass_check_reports_private_members(body: str) -> None:
    """Overriding, replacing, calling or reading a base's underscore member is reported."""
    tree = ast.parse(f'from agent_swarm.sample import Base\nclass Child(Base):\n    {body}\n')

    assert subclass_findings(tree, 'graphtraj.sample', {'graphtraj.sample': tree})


@pytest.mark.usefixtures('sample_base')
def test_subclass_check_follows_graphtraj_classes() -> None:
    """A class below a GraphTraj subclass of an agents class is checked as well."""
    middle = ast.parse('from agent_swarm.sample import Base\nclass Middle(Base):\n    pass\n')
    child = ast.parse('from graphtraj.middle import Middle\nclass Child(Middle):\n    def _hook(self): pass\n')

    assert subclass_findings(child, 'graphtraj.child', {'graphtraj.middle': middle, 'graphtraj.child': child})


@pytest.mark.usefixtures('sample_base')
def test_subclass_check_accepts_own_private_members() -> None:
    """A subclass's own underscore members and the base's public ones are its business."""
    tree = ast.parse('from agent_swarm.sample import Base\n'
                     'class Child(Base):\n'
                     '    def _own(self): pass\n'
                     '    def run(self): self._own()\n')

    assert not subclass_findings(tree, 'graphtraj.sample', {'graphtraj.sample': tree})


JAVASCRIPT_TABLE = {'agent_swarm/pi/extension.mjs': {'loadHostSdk'}}


@pytest.mark.parametrize('source', [
    "import { hidden } from '../../../agent_swarm/pi/extension.mjs';",
    "import {\n  loadHostSdk,\n  hidden,\n} from '../../../agent_swarm/pi/extension.mjs';",
    "export { hidden } from '../../../agent_swarm/pi/extension.mjs';",
    "import { loadHostSdk } from '../../../agent_swarm/pi/session.mjs';",
    "import * as all from '../../../agent_swarm/pi/extension.mjs';",
    "export * from '../../../agent_swarm/pi/extension.mjs';",
    "import everything from '../../../agent_swarm/pi/extension.mjs';",
    "import '../../../agent_swarm/pi/extension.mjs';",
    "const late = await import('../../../agent_swarm/pi/extension.mjs');",
])
def test_javascript_check_reports_unlisted_imports(source: str) -> None:
    """An unlisted file, unlisted export or whole-module import is reported."""
    assert javascript_findings('graphtraj/runtimes/pi/extension.mjs', source, JAVASCRIPT_TABLE)


@pytest.mark.parametrize('source', [
    "import { loadHostSdk } from '../../../agent_swarm/pi/extension.mjs';",
    "import { loadHostSdk as load } from '../../../agent_swarm/pi/extension.mjs';",
    "export { loadHostSdk } from '../../../agent_swarm/pi/extension.mjs';",
    "import { spawn } from 'node:child_process';",
    "import { local } from './collection.mjs';",
])
def test_javascript_check_accepts_listed_exports(source: str) -> None:
    """A listed export and any import outside agents is not reported."""
    assert not javascript_findings('graphtraj/runtimes/pi/extension.mjs', source, JAVASCRIPT_TABLE)
