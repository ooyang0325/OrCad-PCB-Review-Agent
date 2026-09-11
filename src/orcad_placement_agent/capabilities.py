"""Declared backend scope for coordinators; not a live license/readiness probe."""

from . import __version__


def backend_capabilities() -> dict[str, object]:
    return {
        "schema_version": 1,
        "implementation_version": __version__,
        "declaration_only": True,
        "runtime_readiness": "Must be established by inspection of the exact managed session.",
        "native_scope": "fixture_or_managed_unrouted_smt",
        "default_native_model": "fixture",
        "native_models": ["fixture", "managed-board-v1"],
        "native_acceptance": "Managed-board initial placement and mutations require dedicated live acceptance; not established by unit tests.",
        "logical_design_import": False,
        "initial_component_placement": True,
        "initial_placement_model": "managed-board-v1",
        "placement_missions": True,
        "nonrectangular_outline": True,
        "outline_model": "polygon-v1: one simple line/circular-arc contour, no holes or islands",
        "move_existing_component": True,
        "rotate_existing_component": True,
        "supported_target_angles": [0, 90, 180, 270],
        "arbitrary_board_writes": False,
        "route_generation": False,
        "routing_feasibility_verification": False,
        "routing_awareness": "Native pin-based bounded placement planning, reserved corridors and HPWL screening; independent engineering review remains separate.",
        "visual_inspection": True,
        "agent_save_or_undo": True,
        "agent_save_revision": True,
        "agent_undo": False,
        "human_approval_required": True,
        "model_can_authorize_changes": False,
        "portable_writes_enabled_by_default": False,
        "initial_placement_requirements": (
            "Explicit managed-board-v1 staging; nonempty imported logical inventory and embedded simple "
            "top-side SMT footprints; simple closed outline/keepin contours and rectangular keepouts; "
            "millimeters/4/10000; no routing, text, "
            "unmapped logical functions, groups, advanced pads, or nondefault constraint topology. "
            "Native attachments must be readable within the bounded exported-byte model. "
            "Missing definitions and raw empty-design import remain explicit intake blockers. "
            "The legacy fixture model does not initially place components."
        ),
    }
