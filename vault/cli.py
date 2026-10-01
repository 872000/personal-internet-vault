#!/usr/bin/env python3
"""Personal Internet Vault CLI.

    python3 -m vault.cli init
    python3 -m vault.cli import --kind youtube-subs --file subs.csv
    python3 -m vault.cli search "query" [--service youtube] [--kind video]
    python3 -m vault.cli list [--service reddit] [--limit 20]
    python3 -m vault.cli stats
    python3 -m vault.cli export > vault-backup.json
"""

from __future__ import annotations

import argparse
import json
import sys

from .store import VaultStore
from .importers import IMPORTERS, import_file


def _fmt(item) -> str:
    saved = item.saved_at.strftime("%Y-%m-%d")
    tags = ",".join(item.tags[:4])
    line = f"[{item.id}] ({item.service}/{item.kind}) {item.title}"
    if tags:
        line += f"  #{tags}"
    return f"{line}\n    {item.url}  ·  {saved}"


def cmd_import(args) -> int:
    store = VaultStore(args.db)
    try:
        items = import_file(args.kind, args.file)
    except KeyError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except FileNotFoundError:
        print(f"error: file not found: {args.file}", file=sys.stderr)
        return 2
    inserted, updated = store.add_many(items)
    print(f"imported {len(items)} rows from {args.file}: "
          f"{inserted} new, {updated} updated (dedupe by URL)")
    store.close()
    return 0


def cmd_search(args) -> int:
    store = VaultStore(args.db)
    results = store.search(args.query, service=args.service,
                           kind=args.kind, limit=args.limit)
    if not results:
        print("no matches")
    for item in results:
        print(_fmt(item))
    store.close()
    return 0


def cmd_list(args) -> int:
    store = VaultStore(args.db)
    for item in store.list(service=args.service, kind=args.kind,
                           limit=args.limit, offset=args.offset):
        print(_fmt(item))
    store.close()
    return 0


def cmd_stats(args) -> int:
    store = VaultStore(args.db)
    print(json.dumps(store.stats(), indent=2))
    store.close()
    return 0


def cmd_export(args) -> int:
    store = VaultStore(args.db)
    print(store.export_json())
    store.close()
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="vault",
                                description="Personal Internet Vault")
    p.add_argument("--db", default=None,
                   help="vault db path (default: ./data/vault.db)")
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("import", help="import a service export file")
    pi.add_argument("--kind", required=True, choices=sorted(IMPORTERS),
                    help="export format")
    pi.add_argument("--file", required=True, help="path to the export file")
    pi.set_defaults(func=cmd_import)

    ps = sub.add_parser("search", help="full-text search the vault")
    ps.add_argument("query", help="FTS5 query, e.g. \"lofi mix\"")
    ps.add_argument("--service", default=None)
    ps.add_argument("--kind", default=None)
    ps.add_argument("--limit", type=int, default=25)
    ps.set_defaults(func=cmd_search)

    pl = sub.add_parser("list", help="list recent items")
    pl.add_argument("--service", default=None)
    pl.add_argument("--kind", default=None)
    pl.add_argument("--limit", type=int, default=50)
    pl.add_argument("--offset", type=int, default=0)
    pl.set_defaults(func=cmd_list)

    sub.add_parser("stats", help="vault statistics").set_defaults(func=cmd_stats)
    sub.add_parser("export", help="dump vault as JSON").set_defaults(func=cmd_export)
    sub.add_parser("init", help="create the vault database")

    args = p.parse_args(argv)
    if args.cmd == "init":
        store = VaultStore(args.db)
        print(f"vault ready at {store.path}")
        store.close()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
