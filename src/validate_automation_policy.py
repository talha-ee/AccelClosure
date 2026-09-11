#!/usr/bin/env python3

import json
from pathlib import Path


POLICY = Path(
    "configs/product/automation_policy.json"
)


def require(condition, message):
    if not condition:
        raise SystemExit(
            "AUTOMATION_POLICY_INVALID: " + message
        )


def main():
    data = json.loads(
        POLICY.read_text()
    )

    require(
        data["schema"]
        == "accelclosure.automation_policy.v1",
        "wrong schema"
    )

    execution = data["execution"]
    constraints = data["design_constraints"]
    verification = data["verification"]
    timing = data["timing"]
    closure = data["closure_agent"]
    eda = data["eda"]
    failure = data["failure_classification"]
    claims = data["claim_discipline"]

    require(
        execution["unique_run_directory_required"],
        "unique runs must be mandatory"
    )

    require(
        not execution["overwrite_existing_run_artifacts"],
        "artifact overwrite must remain disabled"
    )

    require(
        execution["preserve_every_iteration"],
        "every iteration must be preserved"
    )

    require(
        execution["maximum_closure_iterations"] >= 1,
        "at least one closure iteration required"
    )

    require(
        not constraints["clock_relaxation_allowed"],
        "automatic clock relaxation is forbidden"
    )

    require(
        not constraints[
            "technology_change_during_closure_allowed"
        ],
        "technology must remain fixed"
    )

    require(
        verification[
            "functional_verification_required_before_eda"
        ],
        "functional verification must gate EDA"
    )

    require(
        verification["lint_required_before_eda"],
        "lint must gate EDA"
    )

    require(
        verification["rtl_hash_gate_required_before_eda"],
        "RTL hash gate required"
    )

    require(
        verification["reverify_after_every_rtl_change"],
        "RTL changes must be reverified"
    )

    require(
        timing["prelayout_sta_required"],
        "pre-layout STA required"
    )

    require(
        timing["post_route_timing_required_for_final_closure"],
        "post-route timing required"
    )

    require(
        closure["allowed_failure_class"]
        == "TIMING_ARCHITECTURE",
        "timing closure agent must only repair timing architecture"
    )

    require(
        not eda[
            "mapped_netlist_adapter"
        ]["source_rtl_modification_allowed"],
        "mapped-netlist adapter must never modify RTL"
    )

    require(
        eda[
            "cts_runtime_recovery"
        ]["post_route_setup_revalidation_required"],
        "CTS workaround requires setup revalidation"
    )

    require(
        eda[
            "cts_runtime_recovery"
        ]["post_route_hold_revalidation_required"],
        "CTS workaround requires hold revalidation"
    )

    require(
        failure["UNKNOWN"][
            "stop_automatic_execution"
        ],
        "unknown failures must stop automation"
    )

    require(
        claims[
            "openroad_route_drc_is_not_foundry_signoff_drc"
        ],
        "route DRC cannot be called foundry signoff"
    )

    require(
        claims[
            "gds_generation_is_not_tapeout_signoff"
        ],
        "GDS generation cannot imply tapeout signoff"
    )

    print("AUTOMATION_POLICY_VALID")
    print(
        "MAX_CLOSURE_ITERATIONS="
        + str(
            execution[
                "maximum_closure_iterations"
            ]
        )
    )
    print("CLOCK_RELAXATION_ALLOWED=false")
    print("OVERWRITE_ALLOWED=false")
    print("UNKNOWN_FAILURE_ACTION=STOP")


if __name__ == "__main__":
    main()
