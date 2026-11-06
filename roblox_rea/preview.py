"""Portable, dependency-free top-down SVG map previews for Studio JSON scenes.

This uses oriented box projections only: no Terrain, avatar collision, mesh
triangles, lightmap, textures or screenshot reconstruction is inferred.
"""

from __future__ import annotations

import html
import itertools
from typing import Any

from .schema import validate_scene


def _hull(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    ordered = sorted(set(points))
    if len(ordered) <= 2:
        return ordered

    def cross(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> float:
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    lower: list[tuple[float, float]] = []
    for p in ordered:
        while len(lower) > 1 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper: list[tuple[float, float]] = []
    for p in reversed(ordered):
        while len(upper) > 1 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def _footprint(properties: dict) -> list[tuple[float, float]]:
    cf = properties["cframe"]
    hx, hy, hz = (abs(v) / 2 for v in properties["size"])
    projected = [
        (
            cf[0] + cf[3] * dx + cf[4] * dy + cf[5] * dz,
            -(cf[2] + cf[9] * dx + cf[10] * dy + cf[11] * dz),
        )
        for dx, dy, dz in itertools.product((-hx, hx), (-hy, hy), (-hz, hz))
    ]
    return _hull(projected)


def _color(properties: dict) -> str:
    rgb = properties.get("color")
    if rgb is not None:
        return "#" + "".join(f"{max(0, min(255, round(v * 255))):02x}" for v in rgb)
    palette = {
        "Grass": "#57976b", "Sand": "#c9ae75", "Concrete": "#999ba1",
        "Metal": "#8c9aa7", "Wood": "#a67c52", "Glass": "#8ad4df",
        "Neon": "#9e8cf5", "Water": "#4e9dce", "Slate": "#747e8b",
    }
    return palette.get(properties.get("material"), "#77859a")


def render_svg(scene: dict, max_parts: int = 2500) -> str:
    """Render an SVG that can be opened locally without scripts or external assets."""
    validate_scene(scene)
    if isinstance(max_parts, bool) or not isinstance(max_parts, int) or not 1 <= max_parts <= 15_000:
        raise ValueError("max_parts must be between 1 and 15,000")
    parts: list[dict[str, Any]] = []
    for node in scene["nodes"]:
        p = node.get("properties", {})
        if "size" not in p or "cframe" not in p:
            continue
        polygon = _footprint(p)
        if len(polygon) < 3:
            continue
        xs, zs = zip(*polygon)
        parts.append({
            "node": node,
            "p": p,
            "polygon": polygon,
            "area": (max(xs) - min(xs)) * (max(zs) - min(zs)),
        })
    if not parts:
        raise ValueError("No geometry with Size and CFrame found in this map")
    # Draw big floors/background first, and thin details above them.
    parts.sort(key=lambda item: (-item["area"], item["node"].get("path", item["node"]["id"])))
    chosen = parts[:max_parts]
    all_x = [x for part in chosen for x, _ in part["polygon"]]
    all_z = [z for part in chosen for _, z in part["polygon"]]
    min_x, max_x = min(all_x), max(all_x)
    min_z, max_z = min(all_z), max(all_z)
    width, height = max(max_x - min_x, 0.1), max(max_z - min_z, 0.1)
    # ViewBox uses world studs, plus room for a header regardless of map size.
    padding = max(width, height) * 0.06 + 3
    title_height = max(width, height) * 0.075 + 6
    left, top = min_x - padding, min_z - padding - title_height
    vb_width, vb_height = width + 2 * padding, height + 2 * padding + title_height
    font_size = max(min(vb_width / 35, 16), 2)
    output = [
        '<svg xmlns="http://www.w3.org/2000/svg" role="img" '
        f'width="1200" height="{max(1, round(1200 * vb_height / vb_width))}" '
        f'viewBox="{left:.5f} {top:.5f} {vb_width:.5f} {vb_height:.5f}">',
        '<title>' + html.escape(scene["scene_name"]) + ' · ROBLOX-REA top-down preview</title>',
        f'<rect x="{left:.5f}" y="{top:.5f}" width="{vb_width:.5f}" height="{vb_height:.5f}" fill="#111827"/>',
        f'<text x="{min_x:.5f}" y="{top + title_height * 0.7:.5f}" fill="#eaf0f8" '
        f'font-family="Arial,sans-serif" font-size="{font_size:.4f}" font-weight="bold">'
        + html.escape(scene["scene_name"][:100]) + '</text>',
        f'<text x="{min_x:.5f}" y="{max_z + padding * 0.65:.5f}" fill="#9cacc5" '
        f'font-family="Arial,sans-serif" font-size="{max(font_size * 0.6, 1):.4f}">'
        f'{len(chosen)} / {len(parts)} projected parts · X → right · -Z → up · geometry approximation</text>',
    ]
    for entry in chosen:
        node, p = entry["node"], entry["p"]
        points = " ".join(f"{x:.5f},{z:.5f}" for x, z in entry["polygon"])
        opacity = 1.0 - max(0.0, min(1.0, p.get("transparency", 0.0))) * 0.85
        stroke = "#eaf0f8" if p.get("can_collide") else "#56647c"
        label = f"{node['name']} ({node['class']}) | {node.get('path', node['id'])}"
        output.append(
            f'<polygon points="{points}" fill="{_color(p)}" fill-opacity="{opacity:.3f}" '
            f'stroke="{stroke}" stroke-width="{max(width, height) / 800:.5f}">'
            f'<title>{html.escape(label)}</title></polygon>'
        )
    output.append('</svg>')
    return "\n".join(output) + "\n"
