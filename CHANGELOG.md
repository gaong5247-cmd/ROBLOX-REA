## 0.5.0 — FIDELITY: observable reconstruction accuracy + script inventory

- Add `roblox_rea/fidelity.py` to compare restored vs original scene JSON with field-level tolerance metrics, 3D position/rotation/size drift, internal-reference path normalization, and hierarchy-node coverage. The metric is explicitly **not** a mesh/terrain/script-body accuracy certification.
- Add read-only `POST /v1/fidelity/{capture_id}`, CLI `rea-rbx fidelity` and MCP `verify_reconstruction`.
- Add Studio button **15 · VERIFY map fidelity** for selected Workspace source or staged root in `ServerStorage.REA_Imports`.
- Add metadata-only, service-scoped Script/LocalScript/ModuleScript inventory with explicit refusal of source/bytecode fields, ≤8,000 entries / 1 MiB, authenticated `POST/GET /v1/scripts`, CLI and read-only MCP operations.
- Add Studio button **16 · Inventory server/client scripts (NO source)** and JSON-level Enabled/RunContext capture for scripts in selected models; fix `safeProperty` so `false` is not accidentally treated as nil.
- Document the v1.0 path for explicitly approved Studio-only edit-time source backup and safe restore, **not implemented** in v0.5.
- Add Python/integration/security tests for accuracy, metadata validation, local authentication and CLI. **Studio runtime testing is still outstanding.**

# Changelog

## 0.4.0 — PHOENIX: Hybrid Reconstruction + Relationship Doctor

- Capture allowlisted instance references (Weld, Motor6D, Attachment, selected constraints, ObjectValue) using two-pass intra-selection IDs; flag external links rather than inventing targets.
- Restore missing supported JSON nodes over a native RBXM root while keeping native MeshPart/CSG geometry, in **ServerStorage staging only**. If native model cannot be deserialized, fall back to explicit approximate JSON with warnings.
- Overlay Studio 3D differences with temporary highlights (green added/yellow changed/red missing bounding ghosts), capped at 60 and cleared on plugin unload.
- Add deterministic, read-only Reconstruction Doctor with constrained property/link operations and manual-review blockers; CLI, local HTTP route and MCP tool.
- Apply only after typing `APPLY REPAIR` and rechecking a fresh `plan_id`, inside Studio Undo recording. No automatic deletion, script execution or Terrain edits.
- Add Python tests for relation integrity, stable reference paths, stale plans, unauthorized HTTP calls and CLI.
- **Python verified; Studio plugin not yet manually tested in Roblox Studio.**


## 0.3.0 — High-fidelity Rescue: Terrain and engine-native assets

- Add `roblox-rea.rescue.v1` manifests linking authorized JSON scans, native model RBXM and TerrainRegion RBXM tiles.
- Extend the Studio plugin to capture Terrain within selected geometry bounds using 32-cell tiles (48-tile limit) and to perform an immediate engine roundtrip check on each serialized tile.
- Stage all restored model and terrain objects in `ServerStorage.REA_Imports` by default; require typing `APPLY TERRAIN` before overwriting voxel Terrain, with Studio Undo recording.
- Save and reconstruct whitelisted Instance tags and typed attributes, and key Lights, Sounds and SurfaceAppearance metadata.
- Add native binary SHA-256 checks, package validation and per-file integrity reporting; `rea-rbx packages`, `rescue`, `verify` CLI commands; authenticated local HTTP routes and read-only MCP tools.
- Add tests for corruption, illegal/overlapping terrain bounds, attribute types, read-only package inspection, HTTP routes and CLI.
- Studio plugin and TerrainRegion binary roundtrip remain **unverified in a live Studio session**; engine version, rights and HTTP size limits can affect completeness.

## 0.2.0 — Studio difference inspector and geometry intelligence

- Add read-only compare-current-Selection Studio action and authenticated `/v1/compare/<capture_id>` endpoint.
- Report property-level modifications including presence/absence changes, without rewriting stored captures.
- Add offline top-down SVG map preview (`rea-rbx preview`) with rotated Part footprints and safe XML escaping.
- Add radius-based world-space bounding-box search (`rea-rbx near`, MCP `nearby_objects`).
- Add reconstruction audit of unsupported classes, mesh placeholders and asset references (`rea-rbx audit`, MCP `audit_map`).
- Preserve closest supported ancestor when reconstructing descendants of unsupported JSON classes.
- Reject unrealistic geometry and transforms to keep analysis finite and bounded.
- Make POST responses close the HTTP connection, preventing unread bodies from being parsed as requests.
- Add feature, security and API tests. Keep Studio plugin preview status until manually tested in Roblox Studio.

## 0.1.0 — Initial map lab

- Studio-local JSON scanner, native `.rbxm` roundtrip, JSON reconstruction, safe Model cloning.
- Authenticated localhost Python bridge, CLI scene audit and read-only MCP service.
