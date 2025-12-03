"""Dev-time helpers for seeding the SQLite/Postgres database."""

from __future__ import annotations

import argparse
from typing import Sequence

from config import settings_from_env
from storage import ChatStorage


def seed_command(*, services: Sequence[str] | None, force: bool) -> None:
    settings = settings_from_env()
    store = ChatStorage(settings.database)
    store.seed_from_environment(force=force, include_services=services)
    print("Seed complete. Providers:")
    for provider in store.list_providers():
        print(f" - {provider.slug} ({provider.service})")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Seed wAwesomeChat provider credentials from .env")
    parser.add_argument("--force", action="store_true", help="overwrite existing credentials if present")
    parser.add_argument(
        "--services",
        nargs="*",
        help="optional list of provider slugs to seed (default: all known providers)",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    seed_command(services=args.services, force=args.force)


if __name__ == "__main__":  # pragma: no cover - manual utility
    main()
