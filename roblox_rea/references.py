"""Allowlisted Roblox Instance reference fields captured by the Studio plugin.

Only links whose target lives inside the selected model are representable. They
are recorded as scene-local node IDs, never as global Roblox paths or scripts.
"""

REFERENCE_FIELDS: dict[str, tuple[str, ...]] = {
    "WeldConstraint": ("Part0", "Part1"),
    "Weld": ("Part0", "Part1"),
    "Motor6D": ("Part0", "Part1"),
    "ManualWeld": ("Part0", "Part1"),
    "Snap": ("Part0", "Part1"),
    "NoCollisionConstraint": ("Part0", "Part1"),
    "RigidConstraint": ("Attachment0", "Attachment1"),
    "HingeConstraint": ("Attachment0", "Attachment1"),
    "BallSocketConstraint": ("Attachment0", "Attachment1"),
    "RopeConstraint": ("Attachment0", "Attachment1"),
    "RodConstraint": ("Attachment0", "Attachment1"),
    "SpringConstraint": ("Attachment0", "Attachment1"),
    "PrismaticConstraint": ("Attachment0", "Attachment1"),
    "CylindricalConstraint": ("Attachment0", "Attachment1"),
    "UniversalConstraint": ("Attachment0", "Attachment1"),
    "PlaneConstraint": ("Attachment0", "Attachment1"),
    "TorsionSpringConstraint": ("Attachment0", "Attachment1"),
    "AlignPosition": ("Attachment0", "Attachment1"),
    "AlignOrientation": ("Attachment0", "Attachment1"),
    "Beam": ("Attachment0", "Attachment1"),
    "Trail": ("Attachment0", "Attachment1"),
    "VectorForce": ("Attachment0",),
    "Torque": ("Attachment0",),
    "LineForce": ("Attachment0", "Attachment1"),
    "AngularVelocity": ("Attachment0",),
    "LinearVelocity": ("Attachment0",),
    "ObjectValue": ("Value",),
}

# Used to validate reference destinations. All other class/property pairs are
# rejected before a capture can enter storage.
BASE_PART_CLASSES = frozenset({
    "Part", "WedgePart", "CornerWedgePart", "TrussPart", "Seat",
    "VehicleSeat", "SpawnLocation", "MeshPart", "UnionOperation",
    "NegateOperation", "IntersectOperation",
})


def link_target_valid(field: str, target_class: str) -> bool:
    if field in ("Part0", "Part1"):
        return target_class in BASE_PART_CLASSES
    if field in ("Attachment0", "Attachment1"):
        return target_class == "Attachment"
    return field == "Value"


def reference_paths(scene: dict, node: dict, lookup: dict[str, str] | None = None) -> dict[str, str]:
    """Resolve captured node-ID links to stable relative paths for comparison."""
    if lookup is None:
        lookup = {item["id"]: item.get("path", item["id"]) for item in scene["nodes"]}
    return {field: lookup[target_id] for field, target_id in node.get("references", {}).items()}
