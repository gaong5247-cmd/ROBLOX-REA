# ROBLOX-REA

**REA-inspired Roblox Studio Map Lab:** scan, back up, compare and reconstruct maps from **projects you own or are authorized to edit**, with local AI/MCP access. Independent project inspired by the [REA](https://github.com/morluto/rea) evidence-driven architecture; written separately, not a fork of REA internals.

> **Status: v0.2, developer preview.** Python unit/integration tests are available. The Studio plugin has not yet been tested inside a live Roblox Studio session. Native RBXM roundtrips and network limits may vary with Studio version and asset rights.

## Features

| Feature | How it works | Fidelity |
| --- | --- | --- |
| Map scan | Reads selected model/folder/part hierarchy, transforms, materials, flags and selected assets | Structured scene JSON (not every property) |
| Native backup | Studio `SerializationService:SerializeInstancesAsync` -> authenticated local bridge -> `.rbxm` file | Highest available for archivable, serializable Studio instances |
| Native restore | Fetches `.rbxm` and calls `DeserializeInstancesAsync` | Studio-native model structure |
| JSON reconstruction | Rebuilds supported Parts, Models, Folders, Decals, Textures, Attachments and SpecialMeshes | Approximate; MeshParts/CSG become placeholders |
| Local copy | Studio `Instance:Clone()` selected model to `ServerStorage` | High fidelity for archivable children |
| AI tools | `rea-rbx mcp`: list, analyze, compare, inspect, audit and spatial search | Read-only evidence from captured scenes |
| Top-down map preview | `rea-rbx preview` renders Part world-space footprints to standalone SVG | Geometry approximation only; no Terrain/mesh triangles |
| Spatial search | `rea-rbx near` finds objects intersecting a query sphere via their axis-aligned bounds | Fast bounding-box proximity, **not** Roblox navigation |
| Fidelity audit | `rea-rbx audit` lists unsupported node types, mesh placeholders, unresolved asset references | Honest report of what JSON reconstruction cannot copy |
| Live difference check | Studio button compares current selection against a saved JSON capture without modifying it | Added/removed/changed hierarchy paths and changed properties |

**Not included:** copying protected experiences you do not own, executor injection, bypassing Roblox permissions, reading non-replicated server data, extracting private scripts, or guaranteed Terrain voxel reconstruction. JSON reconstruction does not recreate scripts. Native RBXM may include scripts in authorized projects; imported objects are placed in `ServerStorage.REA_Imports` for inspection before use.

## Quick start (Windows / macOS / Linux)

Requirements: Python 3.10+, Roblox Studio on the same computer.

```powershell
# Clone and install
 git clone https://github.com/gaong5247-cmd/ROBLOX-REA.git
 cd ROBLOX-REA
 python -m pip install -e .
 rea-rbx serve
```

The bridge prints `Studio plugin token: <64 hex characters>`. Keep the terminal running, and **never publish that token**. The server binds only to `127.0.0.1:8787` and stores captures under `~/.roblox-rea/` (Windows: `%USERPROFILE%\.roblox-rea\`). You can change the storage location with `REA_RBX_DATA_DIR`.

### Install the Studio plugin

1. Open a place you own or are authorized to edit in **Roblox Studio**.
2. Create a normal `Script` temporarily in `ServerStorage`; paste the full code from [`plugin/RobloxREA.plugin.lua`](plugin/RobloxREA.plugin.lua).
3. In Studio, save that script as a **local plugin** (for example from the Plugins ribbon or the script's context menu depending on Studio version). Delete the temporary Script after saving. Do **not** press Play on the temporary Script: its `plugin` context is only available as a plugin.
4. Open the `ROBLOX-REA` toolbar button, paste the local bridge token, and select one **Model**, **Folder** or **BasePart** inside your Workspace.
5. Press **Scan selection → save JSON** and/or **Native backup → RBXM**. The bridge assigns an ID that appears in the plugin.
6. Click **Restore native RBXM** (recommended) or **Reconstruct JSON geometry**. The result goes to `ServerStorage.REA_Imports`, **not** directly to the live Workspace. Review then move it manually.
7. After making changes in Studio, reselect the same map and click **Compare selection ↔ saved capture**. This sends the current geometry snapshot to your local bridge for a **read-only comparison**. It does not overwrite the old snapshot or your map.

Roblox may prompt for permission to allow a Studio plugin to connect to `127.0.0.1`. Allow local access if you trust your own local bridge. If HTTP access is disabled, enable it in **Experience Settings → Security → Allow HTTP Requests**. See [Roblox's HTTP documentation](https://create.roblox.com/docs/cloud-services/http-service).

> **Important:** `SerializeInstancesAsync` is usable only from Studio plugins or supported Open Cloud Luau execution sessions. This is not a LocalScript, command bar script, or Roblox executor script.

## CLI

```powershell
rea-rbx list
rea-rbx native
rea-rbx analyze CAPTURE_ID
rea-rbx find CAPTURE_ID "Goal"
rea-rbx compare BEFORE_CAPTURE_ID AFTER_CAPTURE_ID
rea-rbx analyze examples/sample_scene.json --file
rea-rbx compare first.json second.json --files

# v0.2: visual map preview, proximity search, JSON reconstruction audit
rea-rbx preview examples/sample_scene.json --file --output map_preview.svg
rea-rbx near examples/sample_scene.json 0 3 19 --radius 10 --file
rea-rbx audit examples/sample_scene.json --file
```

### AI / MCP integration

```powershell
python -m pip install -e ".[mcp]"
rea-rbx mcp
```

The MCP server runs over **stdio**. Configure your AI coding agent to launch command `rea-rbx` with argument `mcp`; for example, in an MCP host configuration:

```json
{
  "mcpServers": {
    "roblox-rea": {
      "command": "rea-rbx",
      "args": ["mcp"]
    }
  }
}
```

MCP tools:

- `list_captures(limit)`
- `analyze_map(capture_id)`
- `inspect_objects(capture_id, query, limit)`
- `compare_maps(before_capture_id, after_capture_id)`
- `list_native_exports(limit)`
- `audit_map(capture_id)` — JSON reconstruction gaps and asset references
- `nearby_objects(capture_id, x, y, z, radius, limit, collidable_only)` — approximate bounding-box proximity

The MCP endpoint **never** executes user scripts or scans running games. It only reads captures already stored locally. Evidence is limited to the scanned properties, so an AI should identify unknowns rather than hallucinate missing code or terrain. In v0.2, `compare_maps` also returns property-level `modified_details` (with old/new values).

### v0.2 map preview

The `preview` command generates a **standalone SVG** using bounding footprints projected onto the XZ plane. Open `map_preview.svg` locally in any browser to inspect the scan. Hover a shape to see its hierarchy path. The image uses color/material when captured and outlines collidable parts. The drawing is a schematic, **not a faithful 3D render**: it does not load asset textures or mesh polygons, reproduce Terrain voxels, or infer hidden areas.

### Studio bridge v0.2 HTTP additions

With the same local `X-REA-Token` header as the original endpoints:

- `GET /v1/captures/{capture_id}/audit` — structured JSON reconstruction fidelity report.
- `POST /v1/compare/{capture_id}` — send a `roblox-rea.scene.v1` JSON snapshot and compare it against the stored snapshot; the new snapshot is **never stored**.

The server listens only on `127.0.0.1`, and browser-originated requests are rejected. POST connections close on completion so rejected request bodies are never interpreted as new HTTP requests.

## Architecture

```text
Authorized Roblox Studio project
     └─ RobloxREA.plugin.lua (selected Model/Folder/BasePart)
         ├─ JSON scene snapshot  ────────┐
         ├─ Native RBXM via Studio engine ┼─> 127.0.0.1:8787 (private-token HTTP)
         └─ JSON reconstruction <────────┘             │
                                                        v
                                              ~/.roblox-rea/
                                                captures/*.json
                                                native/*.rbxm
                                                        │
                                              Python analyzer / CLI
                                                        │
                                               MCP (AI read-only)
```

JSON format is versioned as `roblox-rea.scene.v1`, bounded to 15,000 nodes / 12 MiB per capture. v0.2 also rejects invalid colors, nonpositive or implausibly large geometry sizes, and out-of-range CFrame components. It stores hierarchy paths and selected properties, not executable source. The bridge requires an unpredictable local token and rejects browser-origin requests. Native backups are limited to 48 MiB per file. The bridge intentionally provides no public network binding.

## Development and tests

```powershell
python -m unittest discover -s tests -v
python -m compileall roblox_rea
```

The tests cover scene validation, path traversal, material/bounds analysis, detailed capture diff, local token checks, JSON HTTP capture, raw binary backup/restore, rotated spatial bounds, SVG escaping and read-only Studio comparison. CI runs on Windows and Linux using Python 3.10 and 3.12.

## License and attribution

MIT; see [`LICENSE`](LICENSE). Architectural inspiration: [REA / Reverse Engineer Anything](https://github.com/morluto/rea) by morluto (MIT). ROBLOX-REA is independent and is **not** the official REA project or a Roblox Corporation product.
