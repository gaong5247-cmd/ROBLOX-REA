"""Read-only MCP tools for AI agents, patterned after REA's evidence workflow.

Uses the maintained v1 Python SDK for compatibility with Python 3.10.
Only previously captured local documents are exposed; no Roblox process hooks,
executor APIs, network discovery or arbitrary filesystem reads are involved.
"""

from __future__ import annotations

from .analysis import analyze_scene, compare_scenes, find_nodes
from .storage import CaptureStore


def create_mcp():
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:
        raise ImportError("Install MCP support: pip install -e '.[mcp]'") from exc

    mcp = FastMCP("ROBLOX-REA")
    store = CaptureStore()

    @mcp.tool()
    def list_captures(limit: int = 30) -> list[dict]:
        """List stored, owner-authorized Roblox Studio map capture IDs."""
        return store.list_captures(limit)

    @mcp.tool()
    def analyze_map(capture_id: str) -> dict:
        """Report object counts, materials, collision statistics and spatial bounds."""
        return analyze_scene(store.read_capture(capture_id))

    @mcp.tool()
    def inspect_objects(capture_id: str, query: str, limit: int = 30) -> list[dict]:
        """Find scene objects by name, class or hierarchy path, including serialized properties."""
        return find_nodes(store.read_capture(capture_id), query, limit)

    @mcp.tool()
    def compare_maps(before_capture_id: str, after_capture_id: str) -> dict:
        """Compare two stored captures and report added, removed and modified objects."""
        return compare_scenes(store.read_capture(before_capture_id), store.read_capture(after_capture_id))

    @mcp.tool()
    def list_native_exports(limit: int = 30) -> list[dict]:
        """List local native RBXM exports. Does not access or execute their contents."""
        return store.list_native(limit)

    return mcp


def run() -> None:
    create_mcp().run(transport="stdio")
