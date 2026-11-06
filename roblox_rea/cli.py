"""One CLI for local Studio bridge, read-only analysis, and MCP integration."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .analysis import analyze_scene, compare_scenes, find_nodes
from .bridge import DEFAULT_PORT, serve
from .schema import validate_scene
from .storage import CaptureStore


def _pretty(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False))


def _scene(store: CaptureStore, key: str, file: bool) -> dict:
    if file:
        doc = json.loads(Path(key).read_text(encoding="utf-8"))
        return validate_scene(doc)
    return store.read_capture(key)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rea-rbx", description="Roblox Studio map capture and REA-style analysis")
    sub = parser.add_subparsers(dest="command", required=True)
    bridge = sub.add_parser("serve", help="Run an authenticated localhost Studio bridge")
    bridge.add_argument("--port", type=int, default=DEFAULT_PORT)
    sub.add_parser("list", help="List captured scenes")
    sub.add_parser("native", help="List native RBXM exports")
    inspect = sub.add_parser("analyze", help="Analyze a scene by capture ID or JSON filename")
    inspect.add_argument("scene")
    inspect.add_argument("--file", action="store_true")
    diff = sub.add_parser("compare", help="Compare two saved scenes by hierarchy path")
    diff.add_argument("before")
    diff.add_argument("after")
    diff.add_argument("--files", action="store_true")
    find = sub.add_parser("find", help="Search scene object names, classes and hierarchy paths")
    find.add_argument("scene")
    find.add_argument("query")
    find.add_argument("--file", action="store_true")
    sub.add_parser("mcp", help="Run read-only MCP server (requires pip install -e '.[mcp]')")
    args = parser.parse_args(argv)
    try:
        if args.command == "serve":
            if not 1 <= args.port <= 65535:
                raise ValueError("Port must be between 1 and 65535")
            serve(args.port)
            return 0
        if args.command == "mcp":
            from .mcp_server import run
            run()
            return 0
        store = CaptureStore()
        if args.command == "list":
            _pretty(store.list_captures())
        elif args.command == "native":
            _pretty(store.list_native())
        elif args.command == "analyze":
            _pretty(analyze_scene(_scene(store, args.scene, args.file)))
        elif args.command == "compare":
            _pretty(compare_scenes(_scene(store, args.before, args.files), _scene(store, args.after, args.files)))
        elif args.command == "find":
            _pretty(find_nodes(_scene(store, args.scene, args.file), args.query))
        return 0
    except (OSError, ValueError, ImportError, json.JSONDecodeError) as exc:
        print(f"rea-rbx: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
