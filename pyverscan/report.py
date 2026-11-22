"""Formats scan results: a human summary and a JSON document."""

import json
from typing import Dict, List, Optional, Tuple

from .scanner import Finding, SCAN_FLOOR, Unparsable

TARGETS = ["3.8", "3.9", "3.10", "3.11", "3.12"]


def _version_key(version: str) -> Tuple[int, int]:
    major, minor = version.split(".")
    return (int(major), int(minor))


def floor_of(findings: List[Finding]) -> Tuple[str, Optional[str]]:
    """Returns (confirmed floor, possible floor). The confirmed floor is the
    highest version a proven finding needs; the possible floor the highest a
    heuristic one does, when it is higher. With no findings the scan floor
    is the answer, as far as the tool can tell."""
    confirmed = [f.floor for f in findings if f.confirmed]
    possible = [f.floor for f in findings if not f.confirmed]
    confirmed_floor = max(confirmed, key=_version_key) if confirmed else SCAN_FLOOR
    possible_floor = max(possible, key=_version_key) if possible else None
    if possible_floor is not None and _version_key(possible_floor) <= _version_key(confirmed_floor):
        possible_floor = None
    return confirmed_floor, possible_floor


def render(
    findings: List[Finding],
    unparsable: List[Unparsable],
    root: str,
    version: str,
    scanned: int,
) -> str:
    confirmed_floor, possible_floor = floor_of(findings)
    lines: List[str] = []
    lines.append("pyverscan v%s  ·  %s" % (version, root))
    lines.append("")
    lines.append("Summary")
    summary = "  %d finding(s) · confirmed floor %s · %d file(s) scanned" % (
        len(findings),
        confirmed_floor,
        scanned,
    )
    if unparsable:
        summary += " · %d unparsable" % len(unparsable)
    lines.append(summary)
    lines.append("")
    if not findings and not unparsable:
        lines.append(
            "  No version-specific features found — nothing above the scan floor."
        )
    if possible_floor is not None:
        lines.append(
            "  possible floor %s — heuristic findings may need it (their receiver"
            " types are unknown)" % possible_floor
        )
    if unparsable:
        lines.append(
            "  %d file(s) this interpreter cannot parse; they may need a newer"
            " Python still" % len(unparsable)
        )
    if findings:
        lines.append("")
        lines.append("Does it run on?")
        for target in TARGETS:
            runs = _version_key(target) >= _version_key(confirmed_floor)
            maybe = (
                possible_floor is not None
                and runs
                and _version_key(target) < _version_key(possible_floor)
            )
            if runs and maybe:
                mark, note = "✓?", "runs, unless the heuristic findings are real"
            elif runs:
                mark, note = "✓", "runs"
            else:
                mark, note = "✗", "needs %s" % confirmed_floor
            lines.append("  python %s  %s  %s" % (target, mark, note))
        lines.append("")
        lines.append("Findings")
        by_floor: Dict[str, List[Finding]] = {}
        ordered = sorted(findings, key=lambda f: (f.file, f.line))
        ordered.sort(key=lambda f: (_version_key(f.floor), f.confirmed), reverse=True)
        for finding in ordered:
            by_floor.setdefault(finding.floor, []).append(finding)
        for floor in sorted(by_floor, key=_version_key, reverse=True):
            group = by_floor[floor]
            lines.append("  needs %s (%d)" % (floor, len(group)))
            for finding in group[:_TOP]:
                state = "" if finding.confirmed else "  (possible)"
                lines.append(
                    "    %s:%d  %s%s"
                    % (finding.file, finding.line, finding.feature.label, state)
                )
            hidden = len(group) - _TOP
            if hidden > 0:
                lines.append("    … and %d more" % hidden)
    if unparsable:
        lines.append("")
        lines.append("Unparsable here")
        for item in unparsable:
            lines.append("  %s:%d  %s" % (item.file, item.line, item.error))
    return "\n".join(lines)


_TOP = 8


def to_json(
    findings: List[Finding],
    unparsable: List[Unparsable],
    root: str,
    scanned: int,
) -> str:
    confirmed_floor, possible_floor = floor_of(findings)
    document = {
        "root": root,
        "scanned_files": scanned,
        "floor": confirmed_floor,
        "possible_floor": possible_floor,
        "findings": [
            {
                "file": f.file,
                "line": f.line,
                "floor": f.floor,
                "feature": f.feature.label,
                "kind": f.feature.kind,
                "confirmed": f.confirmed,
            }
            for f in findings
        ],
        "unparsable": [
            {"file": u.file, "line": u.line, "error": u.error} for u in unparsable
        ],
    }
    return json.dumps(document, indent=2)
