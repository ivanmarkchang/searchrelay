"""Small local command-line interface."""
import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from .config import TEMPLATE, config_dir, load_config
from .models import SearchRequest
from .router import Router


def emit(value):
    print(json.dumps(value, indent=2, default=str))


async def execute(args):
    config = load_config(args.config)
    async with Router(config) as router:
        if args.command == "status":
            emit(router.status())
            return 0
        response = await router.search(SearchRequest(query=args.query, mode=args.mode, limit=args.limit,
                                      freshness=args.freshness, include_domains=args.include_domain,
                                      exclude_domains=args.exclude_domain, strict_dates=args.strict_dates))
        emit(response.model_dump(mode="json"))
        return {"useful": 0, "empty": 2, "unavailable": 3}[response.status]


def main():
    parser = argparse.ArgumentParser(description="SearchRelay — local-first, free-only search routing")
    parser.add_argument("--config", type=Path, help="Path to config.toml")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="Create configuration without credentials or enabled providers")
    sub.add_parser("status", help="Show local configuration and conservative usage estimates")
    search = sub.add_parser("search")
    search.add_argument("query")
    search.add_argument("--mode", choices=["web", "articles", "video"], default="web")
    search.add_argument("--limit", type=int, default=5)
    search.add_argument("--freshness", choices=["day", "week", "month", "year"])
    search.add_argument("--include-domain", action="append", default=[])
    search.add_argument("--exclude-domain", action="append", default=[])
    search.add_argument("--strict-dates", action="store_true")
    serve = sub.add_parser("serve", help="Start HTTP API on 127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    sub.add_parser("mcp", help="Run the MCP stdio server")
    sub.add_parser("clear-cache", help="Delete cached results and operational events, retaining quota counters")
    args = parser.parse_args()
    try:
        if args.command == "init":
            target = args.config or config_dir() / "config.toml"
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            with target.open("x") as output:
                output.write(TEMPLATE)
            os.chmod(target, 0o600)
            print(f"Created {target}. No providers enabled; review free-plan conditions before enabling.")
            return
        if args.command == "serve":
            from .http import serve
            serve(load_config(args.config), args.port, args.config)
            return
        if args.command == "mcp":
            from .mcp_server import serve
            serve(load_config(args.config))
            return
        if args.command == "clear-cache":
            from .state import State
            state = State(config_dir() / "state.sqlite3")
            try:
                state.db.execute("DELETE FROM cache")
                state.db.execute("DELETE FROM events")
            finally:
                state.close()
            print("Cleared cached results and events. Quota counters and cooldowns retained.")
            return
        sys.exit(asyncio.run(execute(args)))
    except FileExistsError:
        print("Configuration already exists; it was not overwritten.", file=sys.stderr)
        sys.exit(1)
    except ImportError:
        print("Missing optional dependency. Install searchrelay[http,mcp] from this repository.", file=sys.stderr)
        sys.exit(1)
    except (ValueError, OSError):
        print("Invalid configuration, request, or inaccessible local state. Check paths and settings.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
