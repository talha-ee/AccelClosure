#!/usr/bin/env python3

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

SPACE_PATH = (
    ROOT
    / "configs"
    / "product"
    / "design_space_v2.json"
)


def load_json(path):
    if not path.exists():
        raise SystemExit(
            "DESIGN_SPACE_ERROR: missing "
            + str(path)
        )

    return json.loads(
        path.read_text()
    )


def nearest_reference(
    rows,
    columns,
    references,
):
    return min(
        references,
        key=lambda item:
            abs(
                item["rows"]
                - rows
            )
            + abs(
                item["columns"]
                - columns
            )
    )


def determine_backend(
    rows,
    columns,
    dataflow,
    arithmetic,
    references,
):
    for reference in references:

        if (
            reference["rows"] == rows
            and reference["columns"] == columns
            and reference["dataflow"] == dataflow
            and reference["arithmetic"] == arithmetic
        ):
            return {
                "status":
                    "VALIDATED_PHYSICAL_REFERENCE",

                "physical_evidence_available":
                    True,

                "requires_new_eda":
                    False,

                "requires_new_architecture_plugin":
                    False
            }

    if (
        dataflow == "ws"
        and arithmetic == "int8"
    ):
        if rows == columns:
            return {
                "status":
                    "PARAMETRIC_WS_EXTENSION",

                "physical_evidence_available":
                    False,

                "requires_new_eda":
                    True,

                "requires_new_architecture_plugin":
                    False
            }

        return {
            "status":
                "GEOMETRY_ADAPTER_EXTENSION",

            "physical_evidence_available":
                False,

            "requires_new_eda":
                True,

            "requires_new_architecture_plugin":
                True
        }

    if dataflow in (
        "os",
        "is",
    ):
        return {
            "status":
                "DATAFLOW_PLUGIN_EXTENSION",

            "physical_evidence_available":
                False,

            "requires_new_eda":
                True,

            "requires_new_architecture_plugin":
                True
        }

    return {
        "status":
            "ARITHMETIC_PLUGIN_EXTENSION",

        "physical_evidence_available":
            False,

        "requires_new_eda":
            True,

        "requires_new_architecture_plugin":
            True
    }


def build_plan(
    rows,
    columns,
    dataflow,
    arithmetic,
    frequency,
    objective,
):
    space = load_json(
        SPACE_PATH
    )

    geometry = space[
        "geometry"
    ]

    if not (
        geometry["rows"]["minimum"]
        <= rows
        <= geometry["rows"][
            "maximum_product_scope"
        ]
    ):
        raise SystemExit(
            "DESIGN_SPACE_ERROR: rows outside "
            "current product scope"
        )

    if not (
        geometry["columns"]["minimum"]
        <= columns
        <= geometry["columns"][
            "maximum_product_scope"
        ]
    ):
        raise SystemExit(
            "DESIGN_SPACE_ERROR: columns outside "
            "current product scope"
        )

    if dataflow not in space[
        "dataflows"
    ]:
        raise SystemExit(
            "DESIGN_SPACE_ERROR: unsupported dataflow"
        )

    if arithmetic not in space[
        "arithmetic"
    ][
        "types"
    ]:
        raise SystemExit(
            "DESIGN_SPACE_ERROR: unsupported arithmetic"
        )

    if objective not in space[
        "objectives"
    ]:
        raise SystemExit(
            "DESIGN_SPACE_ERROR: unsupported objective"
        )

    if frequency <= 0:
        raise SystemExit(
            "DESIGN_SPACE_ERROR: frequency must be > 0"
        )

    references = space[
        "validated_physical_references"
    ]

    backend = determine_backend(
        rows,
        columns,
        dataflow,
        arithmetic,
        references,
    )

    reference = nearest_reference(
        rows,
        columns,
        references,
    )

    return {
        "schema":
            "accelclosure.design_plan.v1",

        "status":
            "VALID_DESIGN_SPACE_REQUEST",

        "request": {
            "rows":
                rows,

            "columns":
                columns,

            "geometry":
                f"{rows}x{columns}",

            "dataflow":
                dataflow,

            "arithmetic":
                arithmetic,

            "target_frequency_mhz":
                frequency,

            "objective":
                objective
        },

        "architecture": {
            "geometry_type":
                (
                    "square"
                    if rows == columns
                    else "rectangular"
                ),

            "dataflow":
                space[
                    "dataflows"
                ][
                    dataflow
                ][
                    "name"
                ],

            "stationary_tensor":
                space[
                    "dataflows"
                ][
                    dataflow
                ][
                    "stationary_tensor"
                ]
        },

        "backend": backend,

        "nearest_validated_reference": {
            "rows":
                reference["rows"],

            "columns":
                reference["columns"],

            "dataflow":
                reference["dataflow"],

            "arithmetic":
                reference["arithmetic"],

            "evidence":
                reference["evidence"]
        },

        "implementation_pipeline": [
            "design_contract",
            "reference_retrieval",
            "architecture_plugin",
            "rtl_generation",
            "functional_verification",
            "synthesis",
            "static_timing_analysis",
            "agentic_closure_if_required",
            "physical_implementation",
            "postroute_evidence",
            "workload_mapping",
            "objective_aware_recommendation"
        ],

        "evidence_policy": {
            "ppa_reuse_allowed":
                False,

            "new_configuration_requires_verification":
                True,

            "new_configuration_requires_eda":
                backend[
                    "requires_new_eda"
                ],

            "design_space_support_is_not_physical_proof":
                True
        }
    }


def print_plan(plan):
    request = plan[
        "request"
    ]

    backend = plan[
        "backend"
    ]

    reference = plan[
        "nearest_validated_reference"
    ]

    print()
    print(
        "============================================================"
    )

    print(
        " ACCELCLOSURE DESIGN-SPACE PLANNER"
    )

    print(
        "============================================================"
    )

    print()

    print(
        "Requested geometry : "
        + request["geometry"]
    )

    print(
        "Dataflow           : "
        + request["dataflow"].upper()
    )

    print(
        "Arithmetic         : "
        + request["arithmetic"].upper()
    )

    print(
        "Target frequency   : "
        + str(
            request[
                "target_frequency_mhz"
            ]
        )
        + " MHz"
    )

    print(
        "Objective          : "
        + request["objective"]
    )

    print()

    print(
        "DESIGN_SPACE_STATUS="
        + plan["status"]
    )

    print(
        "BACKEND_STATUS="
        + backend["status"]
    )

    print(
        "PHYSICAL_EVIDENCE_AVAILABLE="
        + str(
            backend[
                "physical_evidence_available"
            ]
        )
    )

    print()

    print(
        "Nearest validated physical reference:"
    )

    print(
        "  "
        + str(
            reference["rows"]
        )
        + "x"
        + str(
            reference["columns"]
        )
        + " "
        + reference[
            "dataflow"
        ].upper()
        + " "
        + reference[
            "arithmetic"
        ].upper()
    )

    print()

    if backend[
        "physical_evidence_available"
    ]:

        print(
            "This exact configuration already has "
            "frozen physical evidence."
        )

    else:

        print(
            "This configuration is inside the "
            "AccelClosure product design space,"
        )

        print(
            "but it must generate its own RTL, "
            "verification and EDA evidence."
        )

    if backend[
        "requires_new_architecture_plugin"
    ]:

        print(
            "Architecture-specific plugin/adaptation "
            "is required before implementation."
        )

    print()

    print(
        "No PPA metric will be copied from another "
        "array or dataflow."
    )

    print()

    print(
        "ACCELCLOSURE_DESIGN_PLAN=PASS"
    )


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Plan arbitrary AccelClosure systolic-array "
            "configurations without confusing product "
            "capability with measured physical evidence."
        )
    )

    parser.add_argument(
        "--rows",
        required=True,
        type=int,
    )

    parser.add_argument(
        "--columns",
        required=True,
        type=int,
    )

    parser.add_argument(
        "--dataflow",
        required=True,
        choices=[
            "ws",
            "os",
            "is"
        ],
    )

    parser.add_argument(
        "--arithmetic",
        default="int8",
        choices=[
            "int4",
            "int8",
            "int16",
            "bf16"
        ],
    )

    parser.add_argument(
        "--frequency",
        required=True,
        type=float,
    )

    parser.add_argument(
        "--objective",
        default="balanced",
        choices=[
            "latency",
            "area",
            "energy",
            "balanced"
        ],
    )

    parser.add_argument(
        "--json",
        action="store_true",
    )

    args = parser.parse_args()

    plan = build_plan(
        args.rows,
        args.columns,
        args.dataflow,
        args.arithmetic,
        args.frequency,
        args.objective,
    )

    if args.json:
        print(
            json.dumps(
                plan,
                indent=2
            )
        )

    else:
        print_plan(
            plan
        )


if __name__ == "__main__":
    main()
