"""The curated feature table: what each Python feature needs, and how it is
seen in an AST.

Every entry carries the version it requires. ``confirmed`` findings are ones
the AST can prove (a syntax node, an import, a module-anchored attribute);
``heuristic`` findings look like the feature but could be a user-defined
method or a shadowed name. Both are reported; only the split changes.
"""


class Feature:
    __slots__ = ("floor", "label", "kind", "heuristic")

    def __init__(self, floor: str, label: str, kind: str, heuristic: bool = False) -> None:
        self.floor = floor
        self.label = label
        self.kind = kind  # syntax | annotation | import | name
        self.heuristic = heuristic


# --- syntax: the node itself is the proof -------------------------------

SYNTAX_NODES = {
    "NamedExpr": Feature("3.8", "assignment expression (walrus :=)", "syntax"),
    "Match": Feature("3.10", "structural pattern matching (match/case)", "syntax"),
    "TryStar": Feature("3.11", "except* / ExceptionGroup handling", "syntax"),
    "TypeAlias": Feature("3.12", "type alias statement (type X = ...)", "syntax"),
}

# --- annotation semantics: only proven when annotations evaluate --------

ANNOTATION_FEATURES = {
    "builtin_generics": Feature(
        "3.9", "builtin generics in annotations (list[str])", "annotation"
    ),
    "pep604_union": Feature("3.10", "PEP 604 unions in annotations (X | Y)", "annotation"),
}

# --- imports ------------------------------------------------------------
# module -> floor for a plain `import X`; names -> floor per `from X import N`.

IMPORT_MODULES = {
    "graphlib": Feature("3.9", "graphlib (topological sorting)", "import"),
    "zoneinfo": Feature("3.9", "zoneinfo (IANA time zones)", "import"),
    "tomllib": Feature("3.11", "tomllib (TOML parsing)", "import"),
}

IMPORT_NAMES = {
    ("importlib", "metadata"): Feature(
        "3.9", "importlib.metadata (package metadata)", "import"
    ),
    ("typing", "TypeGuard"): Feature("3.10", "typing.TypeGuard", "import"),
    ("typing", "ParamSpec"): Feature("3.10", "typing.ParamSpec", "import"),
    ("typing", "Concatenate"): Feature("3.10", "typing.Concatenate", "import"),
    ("typing", "TypeAlias"): Feature("3.10", "typing.TypeAlias", "import"),
    ("typing", "Self"): Feature("3.11", "typing.Self", "import"),
    ("typing", "Required"): Feature("3.11", "typing.Required", "import"),
    ("typing", "NotRequired"): Feature("3.11", "typing.NotRequired", "import"),
    ("typing", "TypeVarTuple"): Feature("3.11", "typing.TypeVarTuple", "import"),
    ("typing", "Unpack"): Feature("3.11", "typing.Unpack", "import"),
    ("typing", "override"): Feature("3.12", "typing.override", "import"),
}

# --- module-anchored attributes: receiver is the module's own name -------

ATTRIBUTE_FEATURES = {
    ("functools", "cache"): Feature("3.9", "functools.cache", "name"),
    ("itertools", "pairwise"): Feature("3.10", "itertools.pairwise", "name"),
    ("asyncio", "TaskGroup"): Feature("3.11", "asyncio.TaskGroup", "name"),
    ("asyncio", "timeout"): Feature("3.11", "asyncio.timeout", "name"),
    ("contextlib", "chdir"): Feature("3.11", "contextlib.chdir", "name"),
    ("enum", "StrEnum"): Feature("3.11", "enum.StrEnum", "name"),
    ("datetime", "UTC"): Feature("3.11", "datetime.UTC", "name"),
    ("itertools", "batched"): Feature("3.12", "itertools.batched", "name"),
}

# --- bare names: builtins added in a version (shadowing is possible) -----

BUILTIN_NAMES = {
    "aiter": Feature("3.10", "aiter() builtin", "name", heuristic=True),
    "anext": Feature("3.10", "anext() builtin", "name", heuristic=True),
    "ExceptionGroup": Feature("3.11", "ExceptionGroup builtin", "name", heuristic=True),
    "BaseExceptionGroup": Feature(
        "3.11", "BaseExceptionGroup builtin", "name", heuristic=True
    ),
}

# --- receiver methods: the receiver's type is unknown --------------------

METHOD_FEATURES = {
    "removeprefix": Feature("3.9", "str.removeprefix()", "name", heuristic=True),
    "removesuffix": Feature("3.9", "str.removesuffix()", "name", heuristic=True),
    "bit_count": Feature("3.10", "int.bit_count()", "name", heuristic=True),
}

# pathlib.Path.walk() added in 3.12; walking an attribute chain rooted at a
# Name called `pathlib` makes it near-certain.
PATHLIB_WALK = Feature("3.12", "pathlib.Path.walk()", "name")

# dataclass keywords added in 3.10.
DATACLASS_KEYWORDS = {"slots", "kw_only"}

BUILTIN_GENERIC_NAMES = {"list", "dict", "tuple", "set", "frozenset", "type"}
