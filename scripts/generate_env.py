#!/usr/bin/env python3
from __future__ import annotations

"""
Generate per-environment .env files from config/PROJECT_CONFIG.yaml.

Usage:

  python scripts/generate_env.py dev

This will read the "default" section, overlay the "dev" section, and write
an env file at env/.env.dev containing flat KEY=VALUE pairs. Services can
then consume this via docker compose env_file entries.
"""

import argparse
import os
from pathlib import Path
import re

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO_ROOT / "config" / "PROJECT_CONFIG.yaml"
ENV_DIR = REPO_ROOT / "env"


_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def load_project_config() -> dict[str, dict[str, str]]:
    if not CONFIG_PATH.exists():
        raise SystemExit(f"Config file not found at {CONFIG_PATH}")
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise SystemExit("Top-level of PROJECT_CONFIG.yaml must be a mapping")
    # Ensure all env sections are dicts of str->str
    out: dict[str, dict[str, str]] = {}
    for env_name, section in data.items():
        if not isinstance(section, dict):
            raise SystemExit(f"Section {env_name!r} must be a mapping")
        flat: dict[str, str] = {}
        for k, v in section.items():
            key = str(k)
            if not _KEY_RE.match(key):
                raise SystemExit(f"Invalid env var key: {key!r}")
            flat[key] = "" if v is None else str(v)
        out[str(env_name)] = flat
    return out


def merge_env(defaults: dict[str, str], overrides: dict[str, str]) -> dict[str, str]:
    merged = dict(defaults)
    merged.update(overrides)
    return merged


def write_env_file(env_name: str, values: dict[str, str]) -> Path:
    ENV_DIR.mkdir(parents=True, exist_ok=True)
    path = ENV_DIR / f".env.{env_name}"
    lines = []
    for key in sorted(values.keys()):
        value = values[key]
        needs_quoting = any(c in value for c in (" ", "#", '"', "'", "$", "`", "\\"))
        if needs_quoting:
            escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$").replace("`", "\\`")
            line = f'{key}="{escaped}"'
        else:
            line = f"{key}={value}"
        lines.append(line)
    content = "\n".join(lines) + "\n"
    path.write_text(content, encoding="utf-8")
    path.chmod(0o600)
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate .env from PROJECT_CONFIG.yaml")
    parser.add_argument(
        "env",
        help="Environment name (must match a section in PROJECT_CONFIG.yaml, e.g. dev, prod)",
    )
    args = parser.parse_args()

    config = load_project_config()
    default_section = config.get("default", {})
    target_section = config.get(args.env)
    if target_section is None:
        raise SystemExit(
            f"Environment {args.env!r} not found in PROJECT_CONFIG.yaml "
            f"(available: {', '.join(sorted(config.keys()))})"
        )

    merged = merge_env(default_section, target_section)
    out_path = write_env_file(args.env, merged)
    print(f"Wrote {out_path.relative_to(REPO_ROOT)} with {len(merged)} entries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
