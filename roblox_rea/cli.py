"""One CLI for local Studio bridge, read-only analysis, and MCP integration."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .analysis import analyze_scene, compare_scenes, find_nodes
from .audit import audit_reconstruction
from .doctor import plan_repairs
from .fidelity import assess_fidelity
from .script_inventory import summarize_script_inventory, compare_script_inventories
from .preview import render_svg
from .spatial import query_nearby
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
    sub.add_parser("packages", help="List high-fidelity rescue bundles")
    sub.add_parser("scripts", help="List Studio script inventories (metadata only)")
    inv = sub.add_parser("script-inventory", help="Inspect a Studio script inventory (no code)")
    inv.add_argument("inventory_id")
    inv.add_argument("--details", action="store_true", help="Include script names and positions (no source)")
    scriptdiff = sub.add_parser("script-compare", help="Compare two script metadata inventories")
    scriptdiff.add_argument("before")
    scriptdiff.add_argument("after")
    verify = sub.add_parser("verify", help="Check integrity of a rescue bundle")
    verify.add_argument("package_id")
    rescue = sub.add_parser("rescue", help="Inspect a rescue bundle manifest")
    rescue.add_argument("package_id")
    inspect = sub.add_parser("analyze", help="Analyze a scene by capture ID or JSON filename")
    inspect.add_argument("scene")
    inspect.add_argument("--file", action="store_true")
    diff = sub.add_parser("compare", help="Compare two saved scenes by hierarchy path")
    diff.add_argument("before")
    diff.add_argument("after")
    diff.add_argument("--files", action="store_true")
    fidelity = sub.add_parser("fidelity", help="Measure observable map reconstruction fidelity (metadata only)")
    fidelity.add_argument("reference")
    fidelity.add_argument("restored")
    fidelity.add_argument("--files", action="store_true")
    fidelity.add_argument("--position-tolerance", type=float, default=0.05)
    fidelity.add_argument("--rotation-tolerance", type=float, default=0.1)
    fidelity.add_argument("--size-tolerance", type=float, default=0.05)
    doctor = sub.add_parser("doctor", help="Propose non-destructive repairs between reference and current captures")
    doctor.add_argument("reference")
    doctor.add_argument("current")
    doctor.add_argument("--files", action="store_true")
    doctor.add_argument("--limit", type=int, default=100)
    find = sub.add_parser("find", help="Search scene object names, classes and hierarchy paths")
    find.add_argument("scene")
    find.add_argument("query")
    find.add_argument("--file", action="store_true")
    audit = sub.add_parser("audit", help="Explain JSON reconstruction limitations and missing geometry")
    audit.add_argument("scene")
    audit.add_argument("--file", action="store_true")
    near = sub.add_parser("near", help="List parts whose bounding boxes are within a radius")
    near.add_argument("scene")
    near.add_argument("x", type=float)
    near.add_argument("y", type=float)
    near.add_argument("z", type=float)
    near.add_argument("--radius", type=float, default=20.0)
    near.add_argument("--limit", type=int, default=30)
    near.add_argument("--collidable", action="store_true")
    near.add_argument("--file", action="store_true")
    preview = sub.add_parser("preview", help="Generate standalone top-down SVG from JSON geometry")
    preview.add_argument("scene")
    preview.add_argument("--file", action="store_true")
    preview.add_argument("--output", type=Path, default=Path("map_preview.svg"))
    preview.add_argument("--max-parts", type=int, default=2500)
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
        elif args.command == "packages":
            _pretty(store.list_packages())
        elif args.command == "scripts":
            _pretty(store.list_script_inventories())
        elif args.command == "script-inventory":
            inventory = store.read_script_inventory(args.inventory_id)
            _pretty(inventory if args.details else summarize_script_inventory(inventory))
        elif args.command == "script-compare":
            _pretty(compare_script_inventories(store.read_script_inventory(args.before),
                                               store.read_script_inventory(args.after)))
        elif args.command == "verify":
            result = store.verify_package(args.package_id)
            _pretty(result)
            return 0 if result["ok"] else 2
        elif args.command == "rescue":
            _pretty(store.read_package(args.package_id))
        elif args.command == "analyze":
            _pretty(analyze_scene(_scene(store, args.scene, args.file)))
        elif args.command == "compare":
            _pretty(compare_scenes(_scene(store, args.before, args.files), _scene(store, args.after, args.files)))
        elif args.command == "fidelity":
            _pretty(assess_fidelity(_scene(store, args.reference, args.files),
                                    _scene(store, args.restored, args.files),
                                    position_tolerance=args.position_tolerance,
                                    rotation_tolerance=args.rotation_tolerance,
                                    size_tolerance=args.size_tolerance))
        elif args.command == "doctor":
            _pretty(plan_repairs(_scene(store, args.reference, args.files),
                                 _scene(store, args.current, args.files), args.limit))
        elif args.command == "find":
            _pretty(find_nodes(_scene(store, args.scene, args.file), args.query))
        elif args.command == "audit":
            _pretty(audit_reconstruction(_scene(store, args.scene, args.file)))
        elif args.command == "near":
            _pretty(query_nearby(_scene(store, args.scene, args.file), args.x, args.y, args.z,
                                 args.radius, args.limit, args.collidable))
        elif args.command == "preview":
            svg = render_svg(_scene(store, args.scene, args.file), args.max_parts)
            args.output.write_text(svg, encoding="utf-8")
            _pretty({"output": str(args.output.resolve()), "bytes": len(svg.encode("utf-8"))})
        return 0
    except (OSError, ValueError, ImportError, json.JSONDecodeError) as exc:
        print(f"rea-rbx: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
