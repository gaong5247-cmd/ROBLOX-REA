"""Read-only MCP tools for AI agents, patterned after REA's evidence workflow.

Uses the maintained v1 Python SDK for compatibility with Python 3.10.
Only previously captured local documents are exposed; no Roblox process hooks,
executor APIs, network discovery or arbitrary filesystem reads are involved.
"""

from __future__ import annotations

from .analysis import analyze_scene, compare_scenes, find_nodes
from .audit import audit_reconstruction
from .doctor import plan_repairs
from .fidelity import assess_fidelity
from .script_inventory import summarize_script_inventory, compare_script_inventories
from .spatial import query_nearby
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
    def verify_reconstruction(reference_capture_id: str, restored_capture_id: str,
                              position_tolerance: float = 0.05, rotation_tolerance: float = 0.1) -> dict:
        """Read-only comparison of observable object, transform and relationship fidelity.

        Does not verify Terrain voxel geometry, script source or inaccessible assets.
        """
        return assess_fidelity(store.read_capture(reference_capture_id),
                               store.read_capture(restored_capture_id),
                               position_tolerance=position_tolerance, rotation_tolerance=rotation_tolerance)

    @mcp.tool()
    def list_script_inventories(limit: int = 30) -> list[dict]:
        """List metadata-only inventories from authorized Studio projects; never return Luau source."""
        return store.list_script_inventories(limit)

    @mcp.tool()
    def summarize_scripts(inventory_id: str) -> dict:
        """Count scripts by service and class; no Luau source is captured in v0.5."""
        return summarize_script_inventory(store.read_script_inventory(inventory_id))

    @mcp.tool()
    def inspect_script_locations(inventory_id: str, limit: int = 100) -> dict:
        """Read captured names/paths and service placements; source code was never collected."""
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("limit must be 1..100")
        document = store.read_script_inventory(inventory_id)
        items = document["items"]
        return {"inventory_id": inventory_id, "total": len(items), "items": items[:limit],
                "truncated": len(items) > limit, "includes_source": False}

    @mcp.tool()
    def compare_script_locations(reference_id: str, restored_id: str) -> dict:
        """Report changed script filenames, classes, placements and flags; not source equivalence."""
        return compare_script_inventories(store.read_script_inventory(reference_id),
                                          store.read_script_inventory(restored_id))

    @mcp.tool()
    def propose_map_repairs(reference_capture_id: str, current_capture_id: str,
                            limit: int = 100) -> dict:
        """Read-only repair proposal: no scripts, Terrain editing or automatic execution."""
        return plan_repairs(store.read_capture(reference_capture_id),
                            store.read_capture(current_capture_id), limit)

    @mcp.tool()
    def list_native_exports(limit: int = 30) -> list[dict]:
        """List local native RBXM exports. Does not access or execute their contents."""
        return store.list_native(limit)

    @mcp.tool()
    def list_rescue_packages(limit: int = 30) -> list[dict]:
        """List locally captured high-fidelity Studio packages, including Terrain tile counts."""
        return store.list_packages(limit)

    @mcp.tool()
    def inspect_rescue_package(package_id: str) -> dict:
        """Read a package manifest and provenance; no raw assets or executable scripts."""
        return store.read_package(package_id)

    @mcp.tool()
    def verify_rescue_package(package_id: str) -> dict:
        """Verify SHA-256 of native files and availability of the scene snapshot."""
        return store.verify_package(package_id)

    @mcp.tool()
    def audit_map(capture_id: str) -> dict:
        """Explain what JSON reconstruction preserves, skips or approximates."""
        return audit_reconstruction(store.read_capture(capture_id))

    @mcp.tool()
    def nearby_objects(capture_id: str, x: float, y: float, z: float,
                       radius: float = 20.0, limit: int = 30,
                       collidable_only: bool = False) -> dict:
        """Find objects near a world coordinate using approximate world-space bounding boxes."""
        return query_nearby(store.read_capture(capture_id), x, y, z, radius, limit, collidable_only)

    return mcp


def run() -> None:
    create_mcp().run(transport="stdio")
