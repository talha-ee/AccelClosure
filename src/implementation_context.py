#!/usr/bin/env python3

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

AUTOMATION_POLICY = (
    ROOT / "configs/product/automation_policy.json"
)

PIPELINE_POLICY = (
    ROOT / "configs/product/pipeline_policy.json"
)


def load_json(path: Path):
    return json.loads(path.read_text())


def sha256(path: Path):
    h = hashlib.sha256()

    with path.open("rb") as f:
        for block in iter(
            lambda: f.read(1024 * 1024),
            b"",
        ):
            h.update(block)

    return h.hexdigest()


def rel(path: Path):
    return str(
        path.resolve().relative_to(ROOT)
    )


def resolve_path(text):
    path = Path(text)

    if not path.is_absolute():
        path = ROOT / path

    return path.resolve()


def require(condition, message):
    if not condition:
        raise SystemExit(
            "IMPLEMENTATION_CONTEXT_ERROR: "
            + message
        )


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Freeze one exact AccelClosure RTL "
            "implementation for EDA execution."
        )
    )

    parser.add_argument(
        "--run-context",
        required=True,
        help="Path to run_context.json",
    )

    parser.add_argument(
        "--iteration",
        required=True,
        type=int,
        help=(
            "0 = initial implementation, "
            "1..N = closure iteration"
        ),
    )

    args = parser.parse_args()

    # --------------------------------------------------------
    # Load canonical run.
    # --------------------------------------------------------

    run_context_path = resolve_path(
        args.run_context
    )

    require(
        run_context_path.exists(),
        f"run context not found: "
        f"{run_context_path}"
    )

    run_context = load_json(
        run_context_path
    )

    require(
        run_context.get("schema")
        == "accelclosure.run_context.v1",
        "unsupported run-context schema",
    )

    run_dir = run_context_path.parent
    run_id = run_context["run_id"]

    # --------------------------------------------------------
    # Load automation policy.
    # --------------------------------------------------------

    require(
        AUTOMATION_POLICY.exists(),
        "automation policy missing",
    )

    automation_policy = load_json(
        AUTOMATION_POLICY
    )

    max_iterations = int(
        automation_policy[
            "execution"
        ][
            "maximum_closure_iterations"
        ]
    )

    iteration = args.iteration

    require(
        0 <= iteration <= max_iterations,
        (
            f"iteration {iteration} outside "
            f"allowed range 0..{max_iterations}"
        ),
    )

    # --------------------------------------------------------
    # Resolve implementation-specific directories.
    # --------------------------------------------------------

    if iteration == 0:

        implementation_id = "baseline"

        implementation_root = run_dir

        rtl_dir = (
            run_dir
            / "rtl"
        )

        verification_dir = (
            run_dir
            / "verification"
        )

        eda_dir = (
            run_dir
            / "eda"
        )

        config_dir = (
            ROOT
            / "configs"
            / "generated"
            / run_id
        )

        variant = run_id

        output_path = (
            run_dir
            / "implementation_context.json"
        )

        parent = None

        closure_report = None

    else:

        implementation_id = (
            f"closure_iter{iteration}"
        )

        implementation_root = (
            run_dir
            / "closure"
            / f"iter{iteration}"
        )

        rtl_dir = (
            implementation_root
            / "rtl"
        )

        verification_dir = (
            implementation_root
            / "verification"
        )

        eda_dir = (
            implementation_root
            / "eda"
        )

        config_dir = (
            ROOT
            / "configs"
            / "generated"
            / run_id
            / implementation_id
        )

        variant = (
            f"{run_id}_{implementation_id}"
        )

        output_path = (
            implementation_root
            / "implementation_context.json"
        )

        parent = {
            "iteration":
                iteration - 1,

            "implementation_id":
                (
                    "baseline"
                    if iteration == 1
                    else
                    f"closure_iter{iteration - 1}"
                )
        }

        closure_report = (
            implementation_root
            / "report.json"
        )

    # --------------------------------------------------------
    # Required RTL.
    # --------------------------------------------------------

    pe = (
        rtl_dir
        / "accelclosure_ws_pe.sv"
    )

    array = (
        rtl_dir
        / "accelclosure_ws_array.sv"
    )

    require(
        pe.exists(),
        f"PE RTL missing: {pe}",
    )

    require(
        array.exists(),
        f"array RTL missing: {array}",
    )

    # --------------------------------------------------------
    # Functional verification evidence.
    # --------------------------------------------------------

    verification_summary = (
        verification_dir
        / "summary.json"
    )

    require(
        verification_summary.exists(),
        (
            "functional verification summary "
            f"missing: {verification_summary}"
        ),
    )

    verification = load_json(
        verification_summary
    )

    require(
        verification.get("status")
        == "FUNCTIONALLY_VERIFIED",
        (
            "implementation is not "
            "FUNCTIONALLY_VERIFIED"
        ),
    )

    require(
        "rtl" in verification,
        "verification summary has no RTL hashes",
    )

    expected_pe = verification[
        "rtl"
    ][
        "pe_sha256"
    ]

    expected_array = verification[
        "rtl"
    ][
        "array_sha256"
    ]

    actual_pe = sha256(pe)
    actual_array = sha256(array)

    require(
        actual_pe == expected_pe,
        (
            "PE RTL SHA256 differs from "
            "functionally verified RTL"
        ),
    )

    require(
        actual_array == expected_array,
        (
            "array RTL SHA256 differs from "
            "functionally verified RTL"
        ),
    )

    # --------------------------------------------------------
    # Lint evidence.
    #
    # Existing historical runs did not all use the same
    # filename, so identify known report names without
    # fabricating a PASS.
    # --------------------------------------------------------

    lint_candidates = [
        verification_dir
        / "verilator_lint.json",

        verification_dir
        / "lint.json",
    ]

    lint_report = next(
        (
            path
            for path in lint_candidates
            if path.exists()
        ),
        None,
    )

    # --------------------------------------------------------
    # Ensure we never overwrite an implementation record.
    # --------------------------------------------------------

    require(
        not output_path.exists(),
        (
            "implementation context already "
            f"exists and overwrite is forbidden: "
            f"{output_path}"
        ),
    )

    config_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    eda_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    params = run_context["parameters"]

    # --------------------------------------------------------
    # Freeze exact implementation.
    # --------------------------------------------------------

    context = {
        "schema":
            "accelclosure.implementation_context.v1",

        "created_utc":
            datetime.now(
                timezone.utc
            ).isoformat(),

        "run_id":
            run_id,

        "implementation_id":
            implementation_id,

        "iteration":
            iteration,

        "parent":
            parent,

        "request": {
            "n":
                params["n"],

            "rows":
                params["rows"],

            "cols":
                params["cols"],

            "dataflow":
                params["dataflow"],

            "activation_width":
                params["activation_width"],

            "weight_width":
                params["weight_width"],

            "accumulator_width":
                params["accumulator_width"],

            "technology":
                params["technology"],

            "target_frequency_mhz":
                params[
                    "target_frequency_mhz"
                ],

            "target_period_ns":
                params[
                    "target_period_ns"
                ],

            "optimization_objective":
                params[
                    "optimization_objective"
                ],
        },

        "implementation": {
            "rtl_dir":
                rel(rtl_dir),

            "rtl": {
                "pe": {
                    "path":
                        rel(pe),

                    "sha256":
                        actual_pe,
                },

                "array": {
                    "path":
                        rel(array),

                    "sha256":
                        actual_array,
                },
            },

            "verification": {
                "summary_path":
                    rel(
                        verification_summary
                    ),

                "summary_sha256":
                    sha256(
                        verification_summary
                    ),

                "status":
                    verification["status"],

                "lint_report":
                    (
                        {
                            "path":
                                rel(
                                    lint_report
                                ),

                            "sha256":
                                sha256(
                                    lint_report
                                ),
                        }
                        if lint_report
                        else None
                    ),
            },
        },

        "eda": {
            "technology":
                params["technology"],

            "design_name":
                "accelclosure_ws_array",

            "variant":
                variant,

            "config_dir":
                rel(config_dir),

            "eda_dir":
                rel(eda_dir),

            "results_dir": (
                "orfs_runs/results/"
                f"{params['technology']}/"
                "accelclosure_ws_array/"
                f"{variant}"
            ),

            "reports_dir": (
                "orfs_runs/reports/"
                f"{params['technology']}/"
                "accelclosure_ws_array/"
                f"{variant}"
            ),
        },

        "policies": {
            "automation_policy": {
                "path":
                    rel(
                        AUTOMATION_POLICY
                    ),

                "sha256":
                    sha256(
                        AUTOMATION_POLICY
                    ),
            },

            "pipeline_policy": (
                {
                    "path":
                        rel(
                            PIPELINE_POLICY
                        ),

                    "sha256":
                        sha256(
                            PIPELINE_POLICY
                        ),
                }
                if PIPELINE_POLICY.exists()
                else None
            ),

            "clock_relaxation_allowed":
                False,

            "reuse_other_run_metrics":
                False,
        },

        "provenance": {
            "run_context": {
                "path":
                    rel(
                        run_context_path
                    ),

                "sha256":
                    sha256(
                        run_context_path
                    ),
            },

            "closure_agent_report": (
                {
                    "path":
                        rel(
                            closure_report
                        ),

                    "sha256":
                        sha256(
                            closure_report
                        ),
                }
                if (
                    closure_report
                    and closure_report.exists()
                )
                else None
            ),
        },

        "measurement_status": {
            "synthesis":
                False,

            "prelayout_sta":
                False,

            "physical_design":
                False,

            "post_route_sta":
                False,

            "power":
                False,

            "gds":
                False,
        },
    }

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path.write_text(
        json.dumps(
            context,
            indent=2,
        )
        + "\n"
    )

    print(
        "ACCELCLOSURE_IMPLEMENTATION_CONTEXT_CREATED"
    )

    print(
        "RUN_ID="
        + run_id
    )

    print(
        "IMPLEMENTATION_ID="
        + implementation_id
    )

    print(
        "ITERATION="
        + str(iteration)
    )

    print(
        "VARIANT="
        + variant
    )

    print(
        "VERIFIED_RTL_HASH_GATE=PASS"
    )

    print(
        "LINT_REPORT="
        + (
            rel(lint_report)
            if lint_report
            else "NOT_FOUND"
        )
    )

    print(
        "CONTEXT="
        + rel(output_path)
    )


if __name__ == "__main__":
    main()
