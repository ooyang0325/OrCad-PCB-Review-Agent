"""Declared backend scope for coordinators; not a live license/readiness probe."""

from . import __version__


def backend_capabilities() -> dict[str, object]:
    return {
        "schema_version": 1,
        "implementation_version": __version__,
        "declaration_only": True,
        "runtime_readiness": "Must be established by inspection of the exact managed session.",
        "native_scope": "original_synthetic_fixture",
        "logical_design_import": False,
        "initial_component_placement": False,
        "move_existing_component": True,
        "rotate_existing_component": True,
        "supported_target_angles": [0, 90, 180, 270],
        "arbitrary_board_writes": False,
        "route_generation": False,
        "routing_feasibility_verification": False,
        "routing_awareness": "Advisory planning/review using supplied connectivity, stackup and constraints.",
        "visual_inspection": True,
        "agent_save_or_undo": False,
        "human_approval_required": True,
        "model_can_authorize_changes": False,
        "portable_writes_enabled_by_default": False,
        "initial_placement_gap": (
            "Current agent-accessible native tools reposition already-placed fixture symbols only. "
            "Importing a logical design and placing unplaced symbols require additional backend support "
            "or explicit operator preparation. Fixed fixture construction is test setup, not an "
            "initial-placement API or a replacement for the user's design."
        ),
    }
