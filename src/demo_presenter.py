#!/usr/bin/env python3

import argparse
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

FINAL_REPORT = (
    ROOT
    / "results"
    / "benchmarks"
    / "real_models"
    / "final_benchmark_report.json"
)

MANIFEST = (
    ROOT
    / "results"
    / "benchmarks"
    / "real_models"
    / "final_benchmark_manifest.sha256"
)

ADVISOR = (
    ROOT
    / "src"
    / "workload_advisor.py"
)


MODEL_ALIASES = {
    "tinybert": "TinyBERT-4L-312D",
    "tinyllama": "TinyLlama-1.1B",
    "qwen": "Qwen2.5-1.5B",
}


def load_json(path):
    if not path.exists():
        raise SystemExit(
            "ACCELCLOSURE_DEMO_ERROR: "
            + f"missing {path}"
        )

    return json.loads(
        path.read_text()
    )


def line():
    print(
        "=" * 78
    )


def section(title):
    print()
    print(title)
    print(
        "-" * 78
    )


def advisor_result(
    model,
    scenario,
    objective,
):
    command = [
        sys.executable,
        str(ADVISOR),
        "--model",
        model,
        "--scenario",
        scenario,
        "--objective",
        objective,
        "--json",
    ]

    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    if result.returncode != 0:
        raise SystemExit(
            "ACCELCLOSURE_DEMO_ERROR: "
            + result.stderr
            + result.stdout
        )

    return json.loads(
        result.stdout
    )


def human_number(value):
    value = float(value)

    if value >= 1_000_000_000:
        return (
            f"{value / 1_000_000_000:.3f}B"
        )

    if value >= 1_000_000:
        return (
            f"{value / 1_000_000:.3f}M"
        )

    if value >= 1_000:
        return (
            f"{value / 1_000:.3f}K"
        )

    return str(
        round(
            value,
            3,
        )
    )


def print_header():
    print()
    line()

    print(
        " ACCELCLOSURE"
    )

    print(
        " Agentic Prompt-to-Silicon Design Closure "
        "for AI Accelerators"
    )

    line()


def print_flow():
    section(
        "1. What AccelClosure Does"
    )

    print(
        "Natural-language hardware request"
    )

    print(
        "        ↓"
    )

    print(
        "Design contract + golden-reference retrieval"
    )

    print(
        "        ↓"
    )

    print(
        "Agent-generated parameterized RTL"
    )

    print(
        "        ↓"
    )

    print(
        "Lint + signed INT8 functional verification"
    )

    print(
        "        ↓"
    )

    print(
        "Sky130 synthesis + static timing analysis"
    )

    print(
        "        ↓"
    )

    print(
        "Measured failure classification"
    )

    print(
        "        ↓"
    )

    print(
        "Agentic architecture redesign when required"
    )

    print(
        "        ↓"
    )

    print(
        "Placement + CTS + routing + post-route timing + GDS"
    )

    print(
        "        ↓"
    )

    print(
        "Real-model workload evaluation"
    )

    print(
        "        ↓"
    )

    print(
        "Evidence-backed hardware recommendation"
    )


def print_hardware(report):
    section(
        "2. Physically Closed Hardware"
    )

    print(
        f"{'Array':<8}"
        f"{'Target':>10}"
        f"{'Fmax est.':>12}"
        f"{'Area':>14}"
        f"{'Power':>12}"
        f"{'Setup':>9}"
        f"{'Hold':>8}"
    )

    print(
        f"{'':<8}"
        f"{'(MHz)':>10}"
        f"{'(MHz)':>12}"
        f"{'(mm^2)':>14}"
        f"{'(W)':>12}"
        f"{'viol.':>9}"
        f"{'viol.':>8}"
    )

    for item in report[
        "hardware_designs"
    ]:
        print(
            f"{item['array']:<8}"
            f"{item['target_frequency_mhz']:>10.0f}"
            f"{item['postroute_fmax_estimate_mhz']:>12.2f}"
            f"{item['routed_area_mm2']:>14.6f}"
            f"{item['vectorless_power_w']:>12.4f}"
            f"{item['setup_violations']:>9}"
            f"{item['hold_violations']:>8}"
        )

    print()
    print(
        "All three designs have physically closed "
        "post-route evidence and generated GDS artifacts."
    )


def print_tensor_validation(report):
    section(
        "3. Real Transformer Tensor Validation"
    )

    for item in report[
        "real_tensor_validation"
    ]:
        gemm = item[
            "selected_gemm"
        ]

        print(
            f"{item['model']:<22} "
            f"GEMM "
            f"{gemm['m']}x{gemm['k']}x{gemm['n']:<5} "
            f"exact INT32 across all arrays = "
            f"{str(item['all_arrays_exact_int32']):<5} "
            f"cosine = "
            f"{item['cosine_similarity']:.6f}"
        )

    print()
    print(
        "Scope: actual trained model weights and "
        "real model activations, INT8 quantization, "
        "software-tiled INT32 execution."
    )


def print_request(
    model,
    scenario,
    objective,
):
    section(
        "4. User Workload Request"
    )

    print(
        "Model       : "
        + MODEL_ALIASES[
            model
        ]
    )

    print(
        "Scenario    : "
        + scenario
    )

    print(
        "Objective   : "
        + objective
    )


def print_candidates(result):
    section(
        "5. Candidate Hardware Evaluation"
    )

    print(
        f"{'Array':<8}"
        f"{'Util.':>10}"
        f"{'Latency(us)':>16}"
        f"{'GOPS/mm2':>12}"
        f"{'Area(mm2)':>13}"
        f"{'Power(W)':>11}"
    )

    for item in result[
        "candidates"
    ]:
        print(
            f"{item['array']:<8}"
            f"{item['compute_utilization_percent']:>9.2f}%"
            f"{item['projected_compute_latency_us']:>16.3f}"
            f"{item['effective_gops_per_mm2']:>12.3f}"
            f"{item['routed_area_mm2']:>13.6f}"
            f"{item['vectorless_power_w']:>11.4f}"
        )


def print_recommendation(result):
    section(
        "6. AccelClosure Recommendation"
    )

    recommendation = result[
        "recommendation"
    ]

    print(
        "RECOMMENDED HARDWARE: "
        + recommendation[
            "array"
        ]
    )

    print()

    print(
        "WHY:"
    )

    print(
        recommendation[
            "reason"
        ]
    )


def print_claims():
    section(
        "7. Evidence and Claim Boundaries"
    )

    print(
        "• Timing/Fmax: post-route STA evidence."
    )

    print(
        "• Area: routed standard-cell area."
    )

    print(
        "• Power: ORFS vectorless estimate."
    )

    print(
        "• Energy: vectorless-power × projected "
        "compute-latency proxy."
    )

    print(
        "• Model latency: compute-core projection, "
        "not complete Transformer inference."
    )

    print(
        "• Real tensors: actual trained weights and "
        "real activations, software tiled."
    )

    print(
        "• GDS generation does not imply "
        "foundry signoff or tapeout readiness."
    )


def print_footer():
    print()
    line()

    print(
        " ACCELCLOSURE DEMO RESULT: PASS"
    )

    print(
        " Evidence-backed hardware recommendation complete."
    )

    line()

    print()


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Present the final AccelClosure "
            "hackathon demonstration."
        )
    )

    parser.add_argument(
        "--model",
        required=True,
        choices=[
            "tinybert",
            "tinyllama",
            "qwen",
        ],
    )

    parser.add_argument(
        "--scenario",
        required=True,
        choices=[
            "encoder",
            "prefill",
            "decode",
        ],
    )

    parser.add_argument(
        "--objective",
        required=True,
        choices=[
            "latency",
            "area",
            "energy",
        ],
    )

    args = parser.parse_args()

    report = load_json(
        FINAL_REPORT
    )

    if report.get(
        "status"
    ) != "PASS":
        raise SystemExit(
            "ACCELCLOSURE_DEMO_ERROR: "
            "benchmark report is not PASS"
        )

    if not MANIFEST.exists():
        raise SystemExit(
            "ACCELCLOSURE_DEMO_ERROR: "
            "frozen benchmark manifest missing"
        )

    result = advisor_result(
        args.model,
        args.scenario,
        args.objective,
    )

    print_header()

    print_flow()

    print_hardware(
        report
    )

    print_tensor_validation(
        report
    )

    print_request(
        args.model,
        args.scenario,
        args.objective,
    )

    print_candidates(
        result
    )

    print_recommendation(
        result
    )

    print_claims()

    print_footer()


if __name__ == "__main__":
    main()
