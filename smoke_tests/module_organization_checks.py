"""Import and package-organization safety checks.

These checks protect the current flat ``Modules`` import surface before any
future subpackage migration. They intentionally avoid importing the optional
Textual application module as part of the normal implementation manifest.
"""

from __future__ import annotations

import ast
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
MODULES_ROOT = ROOT / "Modules"
OPTIONAL_TEXTUAL_MODULE = "Modules.lvs_tui_app"


def _module_name(path: Path) -> str:
    relative = path.relative_to(ROOT).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def implementation_module_names() -> list[str]:
    """Return every implementation module, including future subpackages."""
    return sorted(
        _module_name(path)
        for path in MODULES_ROOT.rglob("*.py")
        if path.name != "__init__.py"
    )


def _internal_import_targets(path: Path, known_modules: set[str]) -> set[str]:
    module_name = _module_name(path)
    package_name = module_name if path.name == "__init__.py" else module_name.rpartition(".")[0]
    targets: set[str] = set()
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "Modules" or alias.name.startswith("Modules."):
                    targets.add(alias.name)
            continue
        if not isinstance(node, ast.ImportFrom):
            continue

        if node.level:
            relative_name = "." * node.level + (node.module or "")
            try:
                target = importlib.util.resolve_name(relative_name, package_name)
            except (ImportError, ValueError):
                continue
        else:
            target = node.module or ""

        if target == "Modules" or target.startswith("Modules."):
            targets.add(target)
            if node.module is None or target == "Modules":
                for alias in node.names:
                    candidate = f"{target}.{alias.name}"
                    if candidate in known_modules:
                        targets.add(candidate)

    resolved: set[str] = set()
    for target in targets:
        candidate = target
        while candidate.startswith("Modules."):
            if candidate in known_modules:
                resolved.add(candidate)
                break
            candidate = candidate.rpartition(".")[0]
    return resolved


def _strongly_connected_components(graph: dict[str, set[str]]) -> list[list[str]]:
    index = 0
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    components: list[list[str]] = []

    def visit(module: str) -> None:
        nonlocal index
        indices[module] = index
        lowlinks[module] = index
        index += 1
        stack.append(module)
        on_stack.add(module)

        for dependency in graph[module]:
            if dependency not in indices:
                visit(dependency)
                lowlinks[module] = min(lowlinks[module], lowlinks[dependency])
            elif dependency in on_stack:
                lowlinks[module] = min(lowlinks[module], indices[dependency])

        if lowlinks[module] != indices[module]:
            return
        component: list[str] = []
        while True:
            dependency = stack.pop()
            on_stack.remove(dependency)
            component.append(dependency)
            if dependency == module:
                break
        components.append(sorted(component))

    for module in sorted(graph):
        if module not in indices:
            visit(module)
    return components


def _run_isolated(code: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-I", "-B", "-c", code],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def _assert_subprocess_passed(result: subprocess.CompletedProcess[str]) -> None:
    assert result.returncode == 0, (
        f"isolated import check failed with exit code {result.returncode}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


def test_modules_compile_recursively() -> None:
    """Compile all current and future Modules subpackages without source-tree caches."""
    with TemporaryDirectory(prefix="lvs-module-compile-") as cache_dir:
        environment = dict(os.environ)
        environment["PYTHONPYCACHEPREFIX"] = cache_dir
        result = subprocess.run(
            [sys.executable, "-m", "compileall", "-q", str(MODULES_ROOT)],
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
    assert result.returncode == 0, (
        f"recursive Modules compile failed\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


def test_modules_have_no_static_internal_import_cycles() -> None:
    """Reject cycles formed by absolute or relative static Modules imports."""
    paths = sorted(MODULES_ROOT.rglob("*.py"))
    known_modules = {_module_name(path) for path in paths}
    graph = {
        _module_name(path): _internal_import_targets(path, known_modules)
        for path in paths
    }
    cycles = [
        component
        for component in _strongly_connected_components(graph)
        if len(component) > 1 or component[0] in graph[component[0]]
    ]
    assert not cycles, f"static internal import cycles detected: {cycles}"


def test_modules_cold_import_manifest() -> None:
    """Cold-import all practical implementation modules in a fresh interpreter."""
    module_names = [
        name for name in implementation_module_names() if name != OPTIONAL_TEXTUAL_MODULE
    ]
    code = (
        "import importlib, sys\n"
        f"sys.path.insert(0, {str(ROOT)!r})\n"
        f"for name in {module_names!r}: importlib.import_module(name)\n"
    )
    _assert_subprocess_passed(_run_isolated(code))


def test_textual_is_confined_to_optional_tui_boundary() -> None:
    """Prove non-TUI modules import while Textual is unavailable."""
    textual_importers: set[str] = set()
    for path in MODULES_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names: Iterable[str]
            if isinstance(node, ast.Import):
                names = (alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                names = (node.module or "",)
            else:
                continue
            if any(name == "textual" or name.startswith("textual.") for name in names):
                textual_importers.add(_module_name(path))
    assert textual_importers == {OPTIONAL_TEXTUAL_MODULE}, textual_importers

    module_names = [
        name for name in implementation_module_names() if name != OPTIONAL_TEXTUAL_MODULE
    ]
    code = (
        "import importlib, importlib.abc, sys\n"
        f"sys.path.insert(0, {str(ROOT)!r})\n"
        "class BlockTextual(importlib.abc.MetaPathFinder):\n"
        "    def find_spec(self, fullname, path=None, target=None):\n"
        "        if fullname == 'textual' or fullname.startswith('textual.'):\n"
        "            raise ModuleNotFoundError(\"No module named 'textual'\", name='textual')\n"
        "        return None\n"
        "sys.meta_path.insert(0, BlockTextual())\n"
        f"for name in {module_names!r}: importlib.import_module(name)\n"
        "try:\n"
        f"    importlib.import_module({OPTIONAL_TEXTUAL_MODULE!r})\n"
        "except ModuleNotFoundError as error:\n"
        "    if error.name != 'textual': raise\n"
        "else:\n"
        "    raise AssertionError('optional TUI app imported with Textual blocked')\n"
    )
    _assert_subprocess_passed(_run_isolated(code))
