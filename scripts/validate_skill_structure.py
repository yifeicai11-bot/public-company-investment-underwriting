#!/usr/bin/env python3
"""Repository-local structural validation for the bundled Codex skill."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import yaml


NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def validate_skill(skill_dir: Path) -> list[str]:
    errors: list[str] = []
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        return ["SKILL_MD_MISSING"]
    text = skill_md.read_text(encoding="utf-8")
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        return ["SKILL_FRONTMATTER_MISSING"]
    _, frontmatter, body = text.split("---", 2)
    try:
        metadata = yaml.safe_load(frontmatter) or {}
    except yaml.YAMLError as exc:
        return [f"SKILL_FRONTMATTER_INVALID:{type(exc).__name__}"]
    if set(metadata) != {"name", "description"}:
        errors.append("SKILL_FRONTMATTER_KEYS_INVALID")
    name = metadata.get("name")
    if not isinstance(name, str) or len(name) > 64 or not NAME_PATTERN.fullmatch(name):
        errors.append("SKILL_NAME_INVALID")
    description = metadata.get("description")
    if not isinstance(description, str) or not description.strip():
        errors.append("SKILL_DESCRIPTION_MISSING")
    if not body.strip():
        errors.append("SKILL_BODY_MISSING")

    agent_path = skill_dir / "agents" / "openai.yaml"
    if not agent_path.exists():
        errors.append("AGENT_METADATA_MISSING")
    else:
        try:
            agent = yaml.safe_load(agent_path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            errors.append(f"AGENT_METADATA_INVALID:{type(exc).__name__}")
        else:
            interface = agent.get("interface", {})
            prompt = interface.get("default_prompt", "")
            if not all(interface.get(key) for key in ("display_name", "short_description", "default_prompt")):
                errors.append("AGENT_INTERFACE_INCOMPLETE")
            if isinstance(name, str) and f"${name}" not in prompt:
                errors.append("AGENT_DEFAULT_PROMPT_SKILL_NAME_MISSING")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("skill_dir", type=Path)
    args = parser.parse_args()
    errors = validate_skill(args.skill_dir.resolve())
    if errors:
        print("status=SKILL_VALIDATION_FAILED")
        for error in errors:
            print(f"error={error}")
        return 1
    print("status=SKILL_VALIDATED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
