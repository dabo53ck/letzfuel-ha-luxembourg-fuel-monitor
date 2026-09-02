#!/usr/bin/env python3
"""Structural checks for the shipped blueprints.

This is not a full Home Assistant validation (that needs a running HA). It
catches the mistakes that are easy to make by hand:

* YAML syntax errors,
* a missing / incomplete ``blueprint:`` metadata block,
* ``!input`` references that don't match a declared input.

Run: ``python scripts/validate_blueprints.py``
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

BLUEPRINT_DIR = Path(__file__).resolve().parent.parent / "blueprints"
HA_TAGS = ("!input", "!secret", "!env_var", "!include")


class Tagged:
    """A YAML node whose custom tag we keep instead of resolving."""

    __slots__ = ("tag", "value")

    def __init__(self, tag: str, value: Any) -> None:
        self.tag = tag
        self.value = value


class BlueprintLoader(yaml.SafeLoader):
    """SafeLoader that tolerates Home Assistant's custom YAML tags."""


def _keep_scalar(loader: yaml.Loader, node: yaml.Node) -> Tagged:
    return Tagged(node.tag, loader.construct_scalar(node))


for _tag in HA_TAGS:
    BlueprintLoader.add_constructor(_tag, _keep_scalar)


def _collect_inputs(node: Any, found: set[str]) -> None:
    """Walk an ``input:`` mapping, recursing into sections."""
    if not isinstance(node, dict):
        return
    for key, value in node.items():
        if isinstance(value, dict) and "input" in value:
            _collect_inputs(value["input"], found)
        else:
            found.add(key)


def _collect_refs(node: Any, refs: set[str]) -> None:
    if isinstance(node, Tagged):
        if node.tag == "!input":
            refs.add(node.value)
    elif isinstance(node, dict):
        for value in node.values():
            _collect_refs(value, refs)
    elif isinstance(node, list):
        for item in node:
            _collect_refs(item, refs)


def check(path: Path) -> tuple[list[str], list[str]]:
    """Return (errors, warnings) for one blueprint file."""
    try:
        data = yaml.load(path.read_text(encoding="utf-8"), Loader=BlueprintLoader)
    except yaml.YAMLError as err:
        return [f"YAML parse error: {err}"], []

    if not isinstance(data, dict) or not isinstance(data.get("blueprint"), dict):
        return ["missing top-level 'blueprint:' mapping"], []

    errors: list[str] = []
    warnings: list[str] = []
    meta = data["blueprint"]
    for field in ("name", "domain", "source_url"):
        if not meta.get(field):
            errors.append(f"blueprint.{field} is missing")

    declared: set[str] = set()
    _collect_inputs(meta.get("input") or {}, declared)

    refs: set[str] = set()
    _collect_refs({k: v for k, v in data.items() if k != "blueprint"}, refs)

    for ref in sorted(refs - declared):
        errors.append(f"!input {ref} is not a declared input")
    for unused in sorted(declared - refs):
        warnings.append(f"declared input never referenced: {unused}")

    return errors, warnings


def main() -> int:
    files = sorted(BLUEPRINT_DIR.rglob("*.yaml"))
    if not files:
        print("no blueprints found", file=sys.stderr)
        return 1

    failed = False
    for path in files:
        rel = path.relative_to(BLUEPRINT_DIR.parent).as_posix()
        errors, warnings = check(path)
        for warning in warnings:
            print(f"warn {rel}: {warning}")
        if errors:
            failed = True
            print(f"FAIL {rel}")
            for err in errors:
                print(f"  - {err}")
        else:
            print(f"ok   {rel}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
