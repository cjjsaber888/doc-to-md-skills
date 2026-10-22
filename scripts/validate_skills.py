#!/usr/bin/env python3
"""Validate every skill in this repository.

Checks
------
1. Every skills/<name>/ contains a SKILL.md
2. Frontmatter exists and parses as simple key: value lines
3. name and description are present
4. folder name equals frontmatter name
5. name matches ^[a-z0-9][a-z0-9-]*$ and is at most 64 chars
6. description is at most 1024 chars
7. body stays under the 500-line guidance (warning only)
8. no absolute machine path leaked back in (placeholder forms are allowed)

Exit code is 1 when any ERROR is reported, so CI fails on regressions.

Usage
-----
    python scripts/validate_skills.py [--strict]

    --strict  treat warnings as errors
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = ROOT / "skills"

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*(?:\n|$)", re.S)

# Absolute paths that are not placeholders indicate a leak.
LEAK_PATTERNS = [
    re.compile(r"[A-Za-z]:[\\/]Users[\\/](?!<USER>)[^\\/\s\"']+"),
    re.compile(r"/home/(?!<USER>)[^/\s\"']+"),
    re.compile(r"/Users/(?!<USER>)[^/\s\"']+"),
    re.compile(r"[A-Za-z]:[\\/](?!Users)[^\\/\s\"']*[\u4e00-\u9fa5]{2,}"),
]

MAX_BODY_LINES = 500
MAX_DESCRIPTION = 1024
MAX_NAME = 64
SKIP_DIRS = {"__pycache__", ".git", "node_modules"}


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, where: str, msg: str) -> None:
        self.errors.append(f"{where}: {msg}")

    def warn(self, where: str, msg: str) -> None:
        self.warnings.append(f"{where}: {msg}")


def parse_frontmatter(text: str) -> dict[str, str] | None:
    m = FRONTMATTER_RE.match(text)
    if not m:
        return None
    fields: dict[str, str] = {}
    for raw in m.group(1).splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if ":" not in raw:
            continue
        key, _, value = raw.partition(":")
        fields[key.strip()] = value.strip().strip("\"'")
    return fields


def iter_skill_dirs():
    if not SKILLS_DIR.is_dir():
        return []
    return sorted(
        p for p in SKILLS_DIR.iterdir() if p.is_dir() and p.name not in SKIP_DIRS
    )


def scan_leaks(path: Path, rel: str, report: Report) -> None:
    for lineno, line in enumerate(
        path.read_text(encoding="utf-8", errors="replace").splitlines(), 1
    ):
        for pattern in LEAK_PATTERNS:
            for match in pattern.finditer(line):
                report.error(
                    f"{rel}:{lineno}",
                    f"absolute path leaked: {match.group(0)!r}",
                )


def scan_files_for_leaks(skill_dir: Path, report: Report) -> None:
    for path in sorted(skill_dir.rglob("*")):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() not in {".md", ".py", ".json", ".sh", ".txt", ".yml", ".yaml"}:
            continue
        scan_leaks(path, str(path.relative_to(ROOT)).replace("\\", "/"), report)


def validate_skill(skill_dir: Path, report: Report) -> None:
    name = skill_dir.name
    rel = str(skill_dir.relative_to(ROOT)).replace("\\", "/")
    skill_md = skill_dir / "SKILL.md"

    if not skill_md.is_file():
        report.error(rel, "missing SKILL.md at the skill root")
        return

    text = skill_md.read_text(encoding="utf-8", errors="replace")
    fields = parse_frontmatter(text)
    if fields is None:
        report.error(f"{rel}/SKILL.md", "missing or malformed YAML frontmatter")
        return

    fm_name = fields.get("name", "")
    fm_desc = fields.get("description", "")

    if not fm_name:
        report.error(f"{rel}/SKILL.md", "frontmatter is missing 'name'")
    else:
        if fm_name != name:
            report.error(
                f"{rel}/SKILL.md",
                f"frontmatter name {fm_name!r} does not match folder {name!r}",
            )
        if not NAME_RE.match(fm_name):
            report.error(
                f"{rel}/SKILL.md",
                f"name {fm_name!r} must be lowercase hyphen-case matching ^[a-z0-9][a-z0-9-]*$",
            )
        if len(fm_name) > MAX_NAME:
            report.error(f"{rel}/SKILL.md", f"name exceeds {MAX_NAME} chars")

    if not fm_desc:
        report.error(f"{rel}/SKILL.md", "frontmatter is missing 'description'")
    elif len(fm_desc) > MAX_DESCRIPTION:
        report.error(
            f"{rel}/SKILL.md",
            f"description is {len(fm_desc)} chars, limit is {MAX_DESCRIPTION}",
        )

    body_lines = len(text.splitlines())
    if body_lines > MAX_BODY_LINES:
        report.warn(
            f"{rel}/SKILL.md",
            f"{body_lines} lines, guidance is under {MAX_BODY_LINES}",
        )

    scan_files_for_leaks(skill_dir, report)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate skill structure and hygiene.")
    parser.add_argument(
        "--strict", action="store_true", help="treat warnings as errors"
    )
    args = parser.parse_args()

    report = Report()
    dirs = iter_skill_dirs()

    if not dirs:
        print("No skills found under skills/", file=sys.stderr)
        return 1

    for skill_dir in dirs:
        validate_skill(skill_dir, report)

    for line in report.errors:
        print(f"ERROR   {line}")
    for line in report.warnings:
        print(f"WARNING {line}")

    print()
    print(f"skills checked: {len(dirs)}")
    print(f"errors: {len(report.errors)}   warnings: {len(report.warnings)}")

    if report.errors:
        return 1
    if args.strict and report.warnings:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
