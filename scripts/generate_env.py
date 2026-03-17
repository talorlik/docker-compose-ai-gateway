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
from typing import Dict

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO_ROOT / "config" / "PROJECT_CONFIG.yaml"
ENV_DIR = REPO_ROOT / "env"


def load_project_config() -> Dict[str, Dict[str, str]]:
    if not CONFIG_PATH.exists():
        raise SystemExit(f"Config file not found at {CONFIG_PATH}")
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise SystemExit("Top-level of PROJECT_CONFIG.yaml must be a mapping")
    # Ensure all env sections are dicts of str->str
    out: Dict[str, Dict[str, str]] = {}
    for env_name, section in data.items():
        if not isinstance(section, dict):
            raise SystemExit(f"Section {env_name!r} must be a mapping")
        flat: Dict[str, str] = {}
        for k, v in section.items():
            flat[str(k)] = "" if v is None else str(v)
        out[str(env_name)] = flat
    return out


def merge_env(defaults: Dict[str, str], overrides: Dict[str, str]) -> Dict[str, str]:
    merged = dict(defaults)
    merged.update(overrides)
    return merged


def write_env_file(env_name: str, values: Dict[str, str]) -> Path:
    ENV_DIR.mkdir(parents=True, exist_ok=True)
    path = ENV_DIR / f".env.{env_name}"
    lines = []
    for key in sorted(values.keys()):
        value = values[key]
        if any(c in value for c in (" ", "#", '"', "'")):
            # Simple quoting to avoid parsing issues
            escaped = value.replace('"', '\\"')
            line = f'{key}="{escaped}"'
        else:
            line = f"{key}={value}"
        lines.append(line)
    content = "\n".join(lines) + "\n"
    path.write_text(content, encoding="utf-8")
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
