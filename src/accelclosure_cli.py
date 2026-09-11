#!/usr/bin/env python3

import argparse
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

ORCHESTRATOR = (
    ROOT
    / "src"
    / "orchestrator.py"
)

PLANNER = (
    ROOT
    / "src"
    / "design_space_planner.py"
)

ADVISOR = (
    ROOT
    / "src"
    / "workload_advisor.py"
)

DEMO = (
    ROOT
    / "src"
    / "demo_presenter.py"
)

DESIGN_SPACE = (
    ROOT
    / "configs"
    / "product"
    / "design_space_v2.json"
)

FINAL_REPORT = (
    ROOT
    / "results"
    / "benchmarks"
    / "real_models"
    / "final_benchmark_report.json"
)

REFERENCE_CATALOG = (
    ROOT
    / "configs"
    / "product"
    / "reference_catalog.json"
)


def load_json(path):
    if not path.exists():
        raise SystemExit(
            "ACCELCLOSURE_ERROR: missing "
            + str(path)
        )

    return json.loads(
        path.read_text()
    )


def run_child(command):
    result = subprocess.run(
        command
    )

    return result.returncode


def cmd_run(args):
    command = [
        sys.executable,
        str(ORCHESTRATOR),
        args.request,
    ]

    if args.stop_after is not None:
        command.extend(
            [
                "--stop-after",
                args.stop_after,
            ]
        )

    if args.open:
        command.append("--open")

    return run_child(
        command
    )


def cmd_plan(args):
    command = [
        sys.executable,
        str(PLANNER),
        "--rows",
        str(args.rows),
        "--columns",
        str(args.columns),
        "--dataflow",
        args.dataflow,
        "--arithmetic",
        args.arithmetic,
        "--frequency",
        str(args.frequency),
        "--objective",
        args.objective,
    ]

    if args.json:
        command.append(
            "--json"
        )

    return run_child(
        command
    )


def cmd_advise(args):
    command = [
        sys.executable,
        str(ADVISOR),
        "--model",
        args.model,
        "--scenario",
        args.scenario,
        "--objective",
        args.objective,
    ]

    if args.json:
        command.append(
            "--json"
        )

    if args.output is not None:
        command.extend(
            [
                "--output",
                args.output,
            ]
        )

    return run_child(
        command
    )


def cmd_demo(args):
    command = [
        sys.executable,
        str(DEMO),
        "--model",
        args.model,
        "--scenario",
        args.scenario,
        "--objective",
        args.objective,
    ]

    return run_child(
        command
    )


def cmd_status(_args):
    design_space = load_json(
        DESIGN_SPACE
    )

    report = load_json(
        FINAL_REPORT
    )

    references = design_space[
        "validated_physical_references"
    ]

    print()
    print(
        "============================================================"
    )

    print(
        " ACCELCLOSURE STATUS"
    )

    print(
        "============================================================"
    )

    print()

    print(
        "Product:"
    )

    print(
        "  Agentic prompt-to-silicon co-design and "
        "closure framework for systolic AI accelerators"
    )

    print()

    print(
        "Product design space:"
    )

    geometry = design_space[
        "geometry"
    ]

    print(
        "  Geometry    : "
        + str(
            geometry[
                "rows"
            ][
                "minimum"
            ]
        )
        + "x"
        + str(
            geometry[
                "columns"
            ][
                "minimum"
            ]
        )
        + " through "
        + str(
            geometry[
                "rows"
            ][
                "maximum_product_scope"
            ]
        )
        + "x"
        + str(
            geometry[
                "columns"
            ][
                "maximum_product_scope"
            ]
        )
    )

    print(
        "  Shapes      : square + rectangular"
    )

    print(
        "  Dataflows   : WS / OS / IS"
    )

    print(
        "  Arithmetic  : INT4 / INT8 / INT16 / BF16"
    )

    print(
        "  Objectives  : latency / area / energy / balanced"
    )

    print(
        "  Physical backend today : Sky130HD"
    )

    print()

    print(
        "Validated physical references:"
    )

    for reference in references:
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
            + "  "
            + reference[
                "evidence"
            ]
        )

    print()

    print(
        "Measured hardware:"
    )

    for design in report[
        "hardware_designs"
    ]:
        print(
            f"  {design['array']:<6} "
            f"target={design['target_frequency_mhz']:.0f} MHz  "
            f"Fmax-est={design['postroute_fmax_estimate_mhz']:.2f} MHz  "
            f"area={design['routed_area_mm2']:.6f} mm^2  "
            f"power={design['vectorless_power_w']:.4f} W"
        )

    print()

    print(
        "Real-model evidence:"
    )

    for item in report[
        "real_tensor_validation"
    ]:
        print(
            "  "
            + item["model"]
            + "  exact INT32 across validated arrays="
            + str(
                item[
                    "all_arrays_exact_int32"
                ]
            )
        )

    print()

    print(
        "Current implementation maturity:"
    )

    print(
        "  WS INT8 square backend : IMPLEMENTED"
    )

    print(
        "  OS backend             : PLUGIN EXTENSION"
    )

    print(
        "  IS backend             : PLUGIN EXTENSION"
    )

    print(
        "  Rectangular backend    : PLUGIN EXTENSION"
    )

    print(
        "  Other arithmetic       : PLUGIN EXTENSION"
    )

    print()

    print(
        "Important:"
    )

    print(
        "  Product design-space support does not mean "
        "physical evidence already exists."
    )

    print(
        "  Every new configuration must generate its own "
        "verification and EDA evidence."
    )

    print()

    print(
        "ACCELCLOSURE_STATUS=READY"
    )

    return 0


def cmd_explain(args):
    command = [
        sys.executable,
        str(ADVISOR),
        "--model",
        args.model,
        "--scenario",
        args.scenario,
        "--objective",
        args.objective,
        "--json",
    ]

    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    if result.returncode != 0:
        sys.stderr.write(
            result.stderr
        )

        sys.stderr.write(
            result.stdout
        )

        return result.returncode

    data = json.loads(
        result.stdout
    )

    recommendation = data[
        "recommendation"
    ]

    print()
    print(
        "============================================================"
    )

    print(
        " ACCELCLOSURE EXPLANATION"
    )

    print(
        "============================================================"
    )

    print()

    print(
        "Model       : "
        + data[
            "request"
        ][
            "model"
        ]
    )

    print(
        "Scenario    : "
        + data[
            "request"
        ][
            "scenario"
        ]
    )

    print(
        "Objective   : "
        + data[
            "request"
        ][
            "objective"
        ]
    )

    print()

    print(
        "Selected hardware:"
    )

    print(
        "  "
        + recommendation[
            "array"
        ]
    )

    print()

    print(
        "Why AccelClosure selected it:"
    )

    print(
        "  "
        + recommendation[
            "reason"
        ]
    )

    print()

    print(
        "Alternatives considered:"
    )

    for item in data[
        "candidates"
    ]:
        print(
            f"  {item['array']:<6} "
            f"util={item['compute_utilization_percent']:.2f}%  "
            f"latency={item['projected_compute_latency_us']:.3f} us  "
            f"GOPS/mm^2={item['effective_gops_per_mm2']:.3f}  "
            f"area={item['routed_area_mm2']:.6f} mm^2"
        )

    print()

    print(
        "Evidence:"
    )

    print(
        "  Hardware candidates have frozen "
        "post-route evidence."
    )

    print(
        "  Workload performance is an analytical "
        "compute-core projection."
    )

    print(
        "  Energy is a vectorless-power proxy."
    )

    print()

    print(
        "ACCELCLOSURE_EXPLANATION=PASS"
    )

    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        prog="accelclosure",
        description=(
            "AccelClosure: agentic prompt-to-silicon "
            "co-design and design closure for AI accelerators."
        ),
    )

    parser.add_argument(
        "--version",
        action="version",
        version="AccelClosure 0.2.0",
    )

    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
    )

    run_parser = subparsers.add_parser(
        "run",
        help=(
            "Run the autonomous prompt-to-silicon flow "
            "for the currently implemented backend."
        ),
    )

    run_parser.add_argument(
        "request",
        help="Natural-language accelerator request",
    )

    run_parser.add_argument(
        "--stop-after",
        choices=[
            "context",
            "contract",
            "rtl",
            "verification",
            "sta",
            "physical",
        ],
    )

    run_parser.add_argument(
        "--open",
        action="store_true",
        help=(
            "Open the validated final GDS in KLayout "
            "after successful physical closure."
        ),
    )

    run_parser.set_defaults(
        func=cmd_run
    )

    plan_parser = subparsers.add_parser(
        "plan",
        help=(
            "Plan a configuration in the broader "
            "AccelClosure systolic-accelerator design space."
        ),
    )

    plan_parser.add_argument(
        "--rows",
        required=True,
        type=int,
    )

    plan_parser.add_argument(
        "--columns",
        required=True,
        type=int,
    )

    plan_parser.add_argument(
        "--dataflow",
        required=True,
        choices=[
            "ws",
            "os",
            "is",
        ],
    )

    plan_parser.add_argument(
        "--arithmetic",
        default="int8",
        choices=[
            "int4",
            "int8",
            "int16",
            "bf16",
        ],
    )

    plan_parser.add_argument(
        "--frequency",
        required=True,
        type=float,
    )

    plan_parser.add_argument(
        "--objective",
        default="balanced",
        choices=[
            "latency",
            "area",
            "energy",
            "balanced",
        ],
    )

    plan_parser.add_argument(
        "--json",
        action="store_true",
    )

    plan_parser.set_defaults(
        func=cmd_plan
    )

    advise_parser = subparsers.add_parser(
        "advise",
        help=(
            "Recommend a physically validated accelerator "
            "for a real-model workload."
        ),
    )

    advise_parser.add_argument(
        "--model",
        required=True,
        choices=[
            "tinybert",
            "tinyllama",
            "qwen",
        ],
    )

    advise_parser.add_argument(
        "--scenario",
        required=True,
        choices=[
            "encoder",
            "prefill",
            "decode",
        ],
    )

    advise_parser.add_argument(
        "--objective",
        required=True,
        choices=[
            "latency",
            "area",
            "energy",
        ],
    )

    advise_parser.add_argument(
        "--json",
        action="store_true",
    )

    advise_parser.add_argument(
        "--output",
    )

    advise_parser.set_defaults(
        func=cmd_advise
    )

    demo_parser = subparsers.add_parser(
        "demo",
        help="Run the presentation-facing AccelClosure demo.",
    )

    demo_parser.add_argument(
        "--model",
        required=True,
        choices=[
            "tinybert",
            "tinyllama",
            "qwen",
        ],
    )

    demo_parser.add_argument(
        "--scenario",
        required=True,
        choices=[
            "encoder",
            "prefill",
            "decode",
        ],
    )

    demo_parser.add_argument(
        "--objective",
        required=True,
        choices=[
            "latency",
            "area",
            "energy",
        ],
    )

    demo_parser.set_defaults(
        func=cmd_demo
    )

    status_parser = subparsers.add_parser(
        "status",
        help="Show AccelClosure product and evidence status.",
    )

    status_parser.set_defaults(
        func=cmd_status
    )

    explain_parser = subparsers.add_parser(
        "explain",
        help="Explain an evidence-backed hardware recommendation.",
    )

    explain_parser.add_argument(
        "--model",
        required=True,
        choices=[
            "tinybert",
            "tinyllama",
            "qwen",
        ],
    )

    explain_parser.add_argument(
        "--scenario",
        required=True,
        choices=[
            "encoder",
            "prefill",
            "decode",
        ],
    )

    explain_parser.add_argument(
        "--objective",
        required=True,
        choices=[
            "latency",
            "area",
            "energy",
        ],
    )

    explain_parser.set_defaults(
        func=cmd_explain
    )

    return parser


def main():
    parser = build_parser()

    args = parser.parse_args()

    return args.func(
        args
    )


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
