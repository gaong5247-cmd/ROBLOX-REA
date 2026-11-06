# Changelog

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
