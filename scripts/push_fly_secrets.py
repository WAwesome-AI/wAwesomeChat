#!/usr/bin/env python3
"""Push secrets from a .env file into Fly.io."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from dotenv import dotenv_values


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Synchronise environment variables from a .env file into Fly.io secrets.",
    )
    parser.add_argument(
        "--app",
        required=True,
        help="Fly.io app name (passed to `fly secrets set --app`).",
    )
    parser.add_argument(
        "--env-file",
        default="src/wawesomechat/.env",
        help="Path to the .env file to mirror as secrets (default: %(default)s).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    env_path = Path(args.env_file).expanduser()
    if not env_path.is_file():
        raise SystemExit(f"Environment file not found: {env_path}")

    values = dotenv_values(env_path)
    if not values:
        raise SystemExit(f"No environment variables found inside {env_path}")

    for key, value in values.items():
        if not value:
            continue
        print(f"Setting secret {key} on Fly app {args.app}...")
        subprocess.run(
            ["fly", "secrets", "set", f"{key}={value}", "--app", args.app],
            check=True,
        )

    print("Done! Deploy with `fly deploy` when you're ready.")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:  # pragma: no cover - CLI usage
        raise SystemExit(exc.returncode) from exc
