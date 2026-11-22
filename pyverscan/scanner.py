"""AST walk that maps Python constructs to the version they require.

One Finding per construct. A finding is ``confirmed`` when the AST proves it
(a syntax node, an import, a module-anchored attribute); ``heuristic`` when a
user-defined method or a shadowed import could produce the same shape.
Annotations are only confirmed when the module does not defer them with
``from __future__ import annotations``, because deferred evaluation makes
``X | Y`` and ``list[str]`` runtime-safe earlier than their floors.

This module must itself run on Python 3.9, so it never names version-gated
AST classes unquoted: a 3.9 interpreter importing it would otherwise crash
on ``ast.Match`` before scanning anything.
"""

import ast
import os
from typing import Iterator, List, Optional, Set, Tuple

from .features import (
    ANNOTATION_FEATURES,
    ATTRIBUTE_FEATURES,
    BUILTIN_GENERIC_NAMES,
    BUILTIN_NAMES,
    DATACLASS_KEYWORDS,
    Feature,
    IMPORT_MODULES,
    IMPORT_NAMES,
    METHOD_FEATURES,
    PATHLIB_WALK,
    SYNTAX_NODES,
)

DEFAULT_EXCLUDES = (
    ".git",
    ".hg",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "__pycache__",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    "build",
    "dist",
    "site-packages",
    ".eggs",
)

# The oldest version the scanner reasons about. A file with no findings runs
# on at least this, as far as the tool can tell.
SCAN_FLOOR = "3.8"

# AST classes that only exist on newer interpreters; resolved once so this
# module itself imports everywhere the tool claims to run.
_TYPE_ALIAS = getattr(ast, "TypeAlias", None)


class Finding:
    __slots__ = ("file", "line", "feature", "confirmed")

    def __init__(self, file: str, line: int, feature: Feature, confirmed: bool) -> None:
        self.file = file
        self.line = line
        self.feature = feature
        self.confirmed = confirmed

    @property
    def floor(self) -> str:
        return self.feature.floor

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        state = "confirmed" if self.confirmed else "possible"
        return "%s:%d %s (%s)" % (self.file, self.line, self.feature.label, state)


class Unparsable:
    """A file this interpreter's parser rejects, so a newer Python is needed
    to even read it. Reported separately: the floor is at least this."""

    __slots__ = ("file", "line", "error")

    def __init__(self, file: str, line: int, error: str) -> None:
        self.file = file
        self.line = line
        self.error = error


def iter_python_files(root: str, excludes: Tuple[str, ...] = DEFAULT_EXCLUDES) -> Iterator[str]:
    skip = set(excludes)
    if os.path.isfile(root):
        if root.endswith(".py"):
            yield root
        return
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in skip)
        for name in sorted(filenames):
            if name.endswith(".py"):
                yield os.path.join(dirpath, name)


def _annotation_root_ids(tree: ast.Module) -> Set[int]:
    """IDs of the outermost nodes sitting in an annotation slot."""
    roots: Set[int] = set()
    for node in ast.walk(tree):
        target = None
        if isinstance(node, ast.AnnAssign):
            target = node.annotation
        elif isinstance(node, ast.arg):
            target = node.annotation
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            target = node.returns
        elif _TYPE_ALIAS is not None and isinstance(node, _TYPE_ALIAS):
            target = node.value
        if target is not None:
            roots.add(id(target))
    return roots


def _in_annotation(node: ast.AST, annotation_roots: Set[int]) -> bool:
    """True when this node sits inside one of the annotation slots."""
    seen: Set[int] = set()
    stack = list(annotation_roots)
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        stack.extend(id(child) for child in ast.iter_child_nodes(_node_by_id.get(current, _MISSING)))
    return id(node) in seen


_MISSING = object()
_node_by_id: "dict[int, ast.AST]" = {}


def _lazy_annotation_ids(tree: ast.Module) -> Set[int]:
    """IDs of nodes whose evaluation a newer Python defers: a type alias's
    value and the annotations of a PEP 695-parameterized function. Features
    inside them are covered by the surrounding 3.12 finding, so they must
    not double-count as confirmed builtin generics or unions."""
    deferred: Set[int] = set()

    def absorb(root: Optional[ast.AST]) -> None:
        if root is None:
            return
        for child in ast.walk(root):
            deferred.add(id(child))

    for node in ast.walk(tree):
        if _TYPE_ALIAS is not None and isinstance(node, _TYPE_ALIAS):
            absorb(node.value)
        elif getattr(node, "type_params", None) and isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            arguments = node.args
            for argument in (
                arguments.posonlyargs
                + arguments.args
                + arguments.kwonlyargs
                + [arguments.vararg, arguments.kwarg]
            ):
                if argument is not None:
                    absorb(argument.annotation)
            absorb(node.returns)
    return deferred


def scan_source(source: str, path: str):
    """Returns (findings, unparsable). ``unparsable`` is None for a file this
    interpreter's parser accepts."""
    _node_by_id.clear()
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as error:
        return [], Unparsable(path, error.lineno or 1, error.msg or str(error))
    for node in ast.walk(tree):
        _node_by_id[id(node)] = node
    annotation_roots = _annotation_root_ids(tree)
    lazy_ids = _lazy_annotation_ids(tree)

    findings: List[Finding] = []
    deferred = _has_deferred_annotations(tree)

    def add(node: ast.AST, feature: Feature, confirmed: bool) -> None:
        line = getattr(node, "lineno", 1) or 1
        findings.append(Finding(path, line, feature, confirmed))

    for node in ast.walk(tree):
        # Syntax nodes.
        node_type = type(node).__name__
        feature = SYNTAX_NODES.get(node_type)
        if feature is not None:
            add(node, feature, confirmed=True)
        # PEP 695 type parameters.
        if getattr(node, "type_params", None):
            add(node, Feature("3.12", "PEP 695 type parameters ([T])", "syntax"), confirmed=True)
        # Positional-only parameters.
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.args.posonlyargs:
            add(node, Feature("3.8", "positional-only parameters (/,)", "syntax"), confirmed=True)
        # dataclass keywords.
        if isinstance(node, ast.ClassDef):
            for decorator in node.decorator_list:
                if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Name):
                    if decorator.func.id == "dataclass":
                        for keyword in decorator.keywords:
                            if keyword.arg in DATACLASS_KEYWORDS:
                                add(
                                    decorator,
                                    Feature("3.10", "dataclass(%s=...)" % keyword.arg, "syntax"),
                                    confirmed=True,
                                )
        # Imports.
        if isinstance(node, ast.Import):
            for alias in node.names:
                feature = IMPORT_MODULES.get(alias.name)
                if feature is not None:
                    add(node, feature, confirmed=True)
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                feature = IMPORT_MODULES.get(module)
                if feature is not None:
                    add(node, feature, confirmed=True)
                feature = IMPORT_NAMES.get((module, alias.name))
                if feature is not None:
                    add(node, feature, confirmed=True)
        # Builtin generics: a runtime subscript on list/dict/... needs 3.9
        # wherever it appears, annotation or not.
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name):
            if node.value.id in BUILTIN_GENERIC_NAMES:
                feature = ANNOTATION_FEATURES["builtin_generics"]
                add(node, feature, confirmed=not deferred and id(node) not in lazy_ids)
        # PEP 604 unions: a BitOr inside an annotation slot.
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
            if id(node) in annotation_roots or _in_annotation(node, annotation_roots):
                feature = ANNOTATION_FEATURES["pep604_union"]
                add(node, feature, confirmed=not deferred and id(node) not in lazy_ids)
        # Module-anchored attributes.
        if isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name):
                feature = ATTRIBUTE_FEATURES.get((node.value.id, node.attr))
                if feature is not None:
                    add(node, feature, confirmed=True)
            else:
                # pathlib.Path.walk(): an attribute chain rooted at the
                # pathlib name, possibly through the Path() constructor call.
                base = node.value
                while isinstance(base, (ast.Attribute, ast.Call)):
                    base = base.func if isinstance(base, ast.Call) else base.value
                if isinstance(base, ast.Name) and base.id == "pathlib" and node.attr == "walk":
                    add(node, PATHLIB_WALK, confirmed=True)
        # Receiver methods whose type is unknown.
        if isinstance(node, ast.Attribute):
            feature = METHOD_FEATURES.get(node.attr)
            if feature is not None:
                add(node, feature, confirmed=False)
        # Bare builtins added in a version.
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            feature = BUILTIN_NAMES.get(node.id)
            if feature is not None:
                add(node, feature, confirmed=False)

    return findings, None


def _has_deferred_annotations(tree: ast.Module) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            for alias in node.names:
                if alias.name == "annotations":
                    return True
    return False


def scan_file(path: str, source: Optional[str] = None) -> Tuple[List[Finding], Optional[Unparsable]]:
    if source is None:
        with open(path, "r", encoding="utf-8") as handle:
            source = handle.read()
    return scan_source(source, path)


def scan_root(
    root: str, excludes: Tuple[str, ...] = DEFAULT_EXCLUDES
) -> Tuple[List[Finding], List[Unparsable], int]:
    findings: List[Finding] = []
    unparsable: List[Unparsable] = []
    scanned = 0
    for path in iter_python_files(root, excludes):
        scanned += 1
        file_findings, file_error = scan_file(path)
        findings.extend(file_findings)
        if file_error is not None:
            unparsable.append(file_error)
    return findings, unparsable, scanned
