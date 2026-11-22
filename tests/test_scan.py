import json
import os
import sys
import tempfile
import unittest

from pyverscan.cli import main
from pyverscan.report import floor_of
from pyverscan.scanner import SCAN_FLOOR, scan_file, scan_root


def scan(source):
    findings, unparsable = scan_file("snippet.py", source)
    return findings, unparsable


def floors(findings):
    return {f.feature.label: f.floor for f in findings}


class ScanTestCase(unittest.TestCase):
    def assert_floor(self, source, floor, label=None):
        findings, error = scan(source)
        self.assertIsNone(error)
        self.assertTrue(findings, "expected at least one finding")
        self.assertEqual(max(f.floor for f in findings if f.confirmed), floor)
        if label:
            self.assertTrue(
                any(label in f.feature.label for f in findings),
                "expected a finding containing %r, got %s"
                % (label, [f.feature.label for f in findings]),
            )


class SyntaxFloors(ScanTestCase):
    def test_walrus_needs_38(self):
        self.assert_floor("if (n := len(x)) > 3:\n    pass\n", "3.8", "walrus")

    def test_positional_only_needs_38(self):
        self.assert_floor("def f(a, b, /, c):\n    return a\n", "3.8", "positional-only")

    def test_match_needs_310(self):
        source = (
            "def f(x):\n    match x:\n        case 1:\n            return 1\n"
        )
        if sys.version_info < (3, 10):
            findings, error = scan(source)
            self.assertEqual(findings, [])
            self.assertIsNotNone(error)
        else:
            self.assert_floor(source, "3.10", "match/case")

    def test_except_star_needs_311(self):
        source = "try:\n    pass\nexcept* ValueError:\n    pass\n"
        if sys.version_info < (3, 11):
            findings, error = scan(source)
            self.assertEqual(findings, [])
            self.assertIsNotNone(error)
        else:
            self.assert_floor(source, "3.11", "except*")

    def test_type_alias_needs_312(self):
        source = "type Vector = list[float]\n"
        if sys.version_info < (3, 12):
            findings, error = scan(source)
            self.assertEqual(findings, [])
            self.assertIsNotNone(error)
        else:
            self.assert_floor(source, "3.12", "type alias statement")

    def test_pep695_generics_needs_312(self):
        source = "def first[T](items: list[T]) -> T:\n    return items[0]\n"
        if sys.version_info < (3, 12):
            findings, error = scan(source)
            self.assertEqual(findings, [])
            self.assertIsNotNone(error)
        else:
            self.assert_floor(source, "3.12", "PEP 695")


class AnnotationFloors(ScanTestCase):
    def test_builtin_generic_annotation_needs_39(self):
        self.assert_floor(
            "def f(items: list[str]) -> None:\n    pass\n",
            "3.9",
            "builtin generics",
        )

    def test_pep604_union_needs_310(self):
        self.assert_floor(
            "def f(x: int | None) -> None:\n    pass\n",
            "3.10",
            "PEP 604",
        )

    def test_union_outside_annotation_is_not_pep604(self):
        findings, _ = scan("value = 1 | 2\n")
        self.assertEqual(
            [f.feature.label for f in findings if "PEP 604" in f.feature.label], []
        )

    def test_future_annotations_make_them_possible(self):
        source = (
            "from __future__ import annotations\n"
            "def f(x: int | None) -> None:\n    pass\n"
        )
        findings, _ = scan(source)
        self.assertFalse(any(f.confirmed for f in findings))
        confirmed_floor, possible_floor = floor_of(findings)
        self.assertEqual(confirmed_floor, SCAN_FLOOR)
        self.assertEqual(possible_floor, "3.10")


class NamedFloors(ScanTestCase):
    def test_removeprefix_is_heuristic(self):
        findings, _ = scan("value = name.removeprefix('x')\n")
        self.assertEqual(floors(findings).get("str.removeprefix()"), "3.9")
        self.assertFalse(findings[0].confirmed)

    def test_functools_cache_is_confirmed(self):
        findings, _ = scan(
            "import functools\n\n@functools.cache\ndef f():\n    return 1\n"
        )
        self.assertEqual(floors(findings).get("functools.cache"), "3.9")
        self.assertTrue(findings[0].confirmed)

    def test_tomllib_import_needs_311(self):
        self.assert_floor("import tomllib\n", "3.11", "tomllib")

    def test_typing_self_needs_311(self):
        self.assert_floor("from typing import Self\n", "3.11", "typing.Self")

    def test_asyncio_taskgroup_needs_311(self):
        findings, _ = scan("import asyncio\n\nasync def f():\n    async with asyncio.TaskGroup() as g:\n        pass\n")
        self.assertEqual(floors(findings).get("asyncio.TaskGroup"), "3.11")

    def test_itertools_batched_needs_312(self):
        findings, _ = scan(
            "import itertools\n\nfor group in itertools.batched(x, 2):\n    pass\n"
        )
        self.assertEqual(floors(findings).get("itertools.batched"), "3.12")

    def test_exception_group_builtin_is_heuristic(self):
        findings, _ = scan("group = ExceptionGroup('msg', [ValueError()])\n")
        self.assertEqual(
            floors(findings).get("ExceptionGroup builtin"), "3.11"
        )
        self.assertFalse(findings[0].confirmed)

    def test_pathlib_walk_chain_needs_312(self):
        findings, _ = scan(
            "import pathlib\n\nfor root, dirs, files in pathlib.Path('.').walk():\n    pass\n"
        )
        self.assertEqual(floors(findings).get("pathlib.Path.walk()"), "3.12")

    def test_dataclass_slots_needs_310(self):
        self.assert_floor(
            "from dataclasses import dataclass\n\n@dataclass(slots=True)\nclass C:\n    x: int\n",
            "3.10",
            "dataclass(slots=...)",
        )

    def test_shadowed_import_is_still_reported(self):
        # The scanner does not resolve imports; a user module named tomllib
        # would be reported too. Documented behavior, not a bug.
        findings, _ = scan("import zoneinfo\n")
        self.assertEqual(floors(findings).get("zoneinfo (IANA time zones)"), "3.9")


class Unparsable(unittest.TestCase):
    def test_match_on_this_interpreter(self):
        # The running interpreter decides: on 3.9 a match statement cannot
        # parse; on 3.10+ it is a 3.10 finding.
        findings, unparsable = scan(
            "def f(x):\n    match x:\n        case 1:\n            return 1\n"
        )
        if sys.version_info >= (3, 10):
            self.assertIsNone(unparsable)
            self.assertTrue(any("match/case" in f.feature.label for f in findings))
        else:
            self.assertEqual(findings, [])
            self.assertIsNotNone(unparsable)


class Gate(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.mkdtemp()
        with open(os.path.join(self.directory, "new.py"), "w") as handle:
            handle.write("def f(x: int | None) -> int:\n    return x or 0\n")

    def test_gate_passes_when_floor_at_or_below_max(self):
        self.assertEqual(main(["--max", "3.10", self.directory]), 0)
        self.assertEqual(main(["--max", "3.11", self.directory]), 0)

    def test_gate_fails_when_floor_above_max(self):
        self.assertEqual(main(["--max", "3.9", self.directory]), 1)

    def test_gate_ignores_heuristic_findings(self):
        directory = tempfile.mkdtemp()
        with open(os.path.join(directory, "maybe.py"), "w") as handle:
            handle.write("value = name.removeprefix('x')\n")
        # Only heuristic findings, all below nothing: a heuristic above --max
        # is reported, not failed on.
        self.assertEqual(main(["--max", "3.8", directory]), 0)


class Json(unittest.TestCase):
    def test_json_document_shape(self):
        directory = tempfile.mkdtemp()
        with open(os.path.join(directory, "code.py"), "w") as handle:
            handle.write("def f(x: int | None) -> int:\n    return x or 0\n")
        import contextlib
        import io

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            main(["--json", directory])
        document = json.loads(buffer.getvalue())
        self.assertEqual(document["floor"], "3.10")
        self.assertEqual(document["scanned_files"], 1)
        self.assertEqual(document["findings"][0]["confirmed"], True)
        self.assertIn("PEP 604", document["findings"][0]["feature"])


class Excludes(unittest.TestCase):
    def test_default_excludes_skip_vendor_directories(self):
        directory = tempfile.mkdtemp()
        os.makedirs(os.path.join(directory, ".venv", "lib"))
        with open(os.path.join(directory, ".venv", "lib", "x.py"), "w") as handle:
            handle.write("import tomllib\n")
        findings, _, scanned = scan_root(directory)
        self.assertEqual(scanned, 0)
        self.assertEqual(findings, [])

    def test_custom_exclude(self):
        directory = tempfile.mkdtemp()
        os.makedirs(os.path.join(directory, "vendor"))
        with open(os.path.join(directory, "vendor", "x.py"), "w") as handle:
            handle.write("import tomllib\n")
        findings, _, scanned = scan_root(directory, ("vendor",))
        self.assertEqual(scanned, 0)


class Floors(unittest.TestCase):
    def test_no_findings_means_scan_floor(self):
        findings, _ = scan("value = 1\n")
        confirmed_floor, possible_floor = floor_of(findings)
        self.assertEqual(confirmed_floor, SCAN_FLOOR)
        self.assertIsNone(possible_floor)

    def test_possible_floor_only_when_higher(self):
        findings, _ = scan(
            "def f(x: int) -> int:\n    return x.bit_count()\n"
        )
        # bit_count is heuristic (3.10) and there is no confirmed finding.
        confirmed_floor, possible_floor = floor_of(findings)
        self.assertEqual(confirmed_floor, SCAN_FLOOR)
        self.assertEqual(possible_floor, "3.10")


if __name__ == "__main__":
    unittest.main()
