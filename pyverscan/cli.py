"""Command line entry point."""

import argparse
import sys
from typing import List, Optional

from . import __version__
from .report import render, to_json
from .scanner import DEFAULT_EXCLUDES, scan_root


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pyverscan",
        description="Scan a Python codebase for the oldest version it can run on.",
    )
    parser.add_argument("root", nargs="?", default=".", help="file or folder to scan")
    parser.add_argument(
        "--max",
        dest="max_version",
        metavar="X.Y",
        default=None,
        help="fail with exit 1 when the confirmed floor is above this version",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="NAME",
        help="skip a directory by name (repeatable; extends the defaults)",
    )
    parser.add_argument("--json", action="store_true", help="print a JSON document")
    parser.add_argument("--version", action="version", version=__version__)
    return parser


def _version_key(version: str):
    major, minor = version.split(".")
    return (int(major), int(minor))


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    options = parser.parse_args(argv)
    if options.max_version is not None:
        try:
            _version_key(options.max_version)
        except (ValueError, AttributeError):
            parser.error("--max expects a version like 3.9")
    excludes = DEFAULT_EXCLUDES + tuple(options.exclude)
    findings, unparsable, scanned = scan_root(options.root, excludes)
    if options.json:
        print(to_json(findings, unparsable, options.root, scanned))
    else:
        print(render(findings, unparsable, options.root, __version__, scanned))
    if options.max_version is None:
        return 0
    confirmed = [f.floor for f in findings if f.confirmed]
    if not confirmed:
        return 0
    floor = max(confirmed, key=_version_key)
    if _version_key(floor) > _version_key(options.max_version):
        sys.stderr.write(
            "pyverscan: floor %s is above --max %s\n" % (floor, options.max_version)
        )
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
