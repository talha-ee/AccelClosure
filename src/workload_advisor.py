#!/usr/bin/env python3

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

REPORT_PATH = (
    ROOT
    / "results"
    / "benchmarks"
    / "real_models"
    / "final_benchmark_report.json"
)

PROJECTION_PATH = (
    ROOT
    / "results"
    / "benchmarks"
    / "real_models"
    / "projection_results.json"
)


MODEL_ALIASES = {
    "tinybert":
        "TinyBERT-4L-312D",

    "tinyllama":
        "TinyLlama-1.1B",

    "qwen":
        "Qwen2.5-1.5B",

    "qwen2.5":
        "Qwen2.5-1.5B",
}


SCENARIO_ALIASES = {
    "encoder":
        "encoder_seq128",

    "prefill":
        "prefill_128",

    "decode":
        "decode_1_ctx128",

    "encoder_seq128":
        "encoder_seq128",

    "prefill_128":
        "prefill_128",

    "decode_1_ctx128":
        "decode_1_ctx128",
}


OBJECTIVES = {
    "latency":
        "projected_compute_latency_us_at_target",

    "area":
        "effective_gops_per_mm2",

    "energy":
        "vectorless_energy_proxy_mj",
}


def load_json(path):
    if not path.exists():
        raise SystemExit(
            "ACCELCLOSURE_ADVISOR_ERROR: "
            + f"missing evidence file: {path}"
        )

    return json.loads(
        path.read_text()
    )


def canonical_model(value):
    key = value.strip().lower()

    if key not in MODEL_ALIASES:
        raise SystemExit(
            "ACCELCLOSURE_ADVISOR_ERROR: "
            + "unsupported model "
            + repr(value)
        )

    return MODEL_ALIASES[key]


def canonical_scenario(
    model,
    value,
):
    key = value.strip().lower()

    if key not in SCENARIO_ALIASES:
        raise SystemExit(
            "ACCELCLOSURE_ADVISOR_ERROR: "
            + "unsupported scenario "
            + repr(value)
        )

    scenario = SCENARIO_ALIASES[key]

    if (
        model == "TinyBERT-4L-312D"
        and scenario != "encoder_seq128"
    ):
        raise SystemExit(
            "ACCELCLOSURE_ADVISOR_ERROR: "
            + "TinyBERT benchmark supports "
            + "encoder_seq128."
        )

    if (
        model != "TinyBERT-4L-312D"
        and scenario == "encoder_seq128"
    ):
        raise SystemExit(
            "ACCELCLOSURE_ADVISOR_ERROR: "
            + "decoder models support "
            + "prefill_128 or decode_1_ctx128."
        )

    return scenario


def find_rows(
    projection,
    model,
    scenario,
):
    rows = [
        item
        for item in projection["results"]
        if (
            item["model"] == model
            and
            item["scenario"] == scenario
        )
    ]

    if len(rows) != 3:
        raise SystemExit(
            "ACCELCLOSURE_ADVISOR_ERROR: "
            + "expected exactly three "
            + "hardware candidates"
        )

    return rows


def choose(
    rows,
    objective,
):
    metric = OBJECTIVES[
        objective
    ]

    if objective == "area":
        return max(
            rows,
            key=lambda item:
                float(
                    item[metric]
                ),
        )

    return min(
        rows,
        key=lambda item:
            float(
                item[metric]
            ),
    )


def explain(
    rows,
    winner,
    objective,
    scenario,
):
    ordered = sorted(
        rows,
        key=lambda item:
            int(
                item["array_n"]
            ),
    )

    if objective == "latency":
        winner_latency = float(
            winner[
                "projected_compute_latency_us_at_target"
            ]
        )

        competitors = [
            float(
                item[
                    "projected_compute_latency_us_at_target"
                ]
            )
            for item in rows
            if item["array"] != winner["array"]
        ]

        next_best = min(
            competitors
        )

        speedup = (
            next_best
            / winner_latency
        )

        return (
            f"{winner['array']} has the lowest "
            f"projected compute-core latency at its "
            f"physically closed target clock. "
            f"It is approximately {speedup:.2f}x faster "
            f"than the next-fastest tested candidate "
            f"for this workload projection."
        )

    if objective == "area":
        value = float(
            winner[
                "effective_gops_per_mm2"
            ]
        )

        if scenario == "decode_1_ctx128":
            util_text = ", ".join(
                (
                    item["array"]
                    + "="
                    + f"{100.0 * float(item['compute_utilization']):.2f}%"
                )
                for item in ordered
            )

            return (
                f"{winner['array']} provides the highest "
                f"effective throughput per routed cell area "
                f"({value:.3f} GOPS/mm^2). "
                f"Decode uses M=1, so spatial utilization "
                f"drops as the array grows: {util_text}."
            )

        return (
            f"{winner['array']} provides the highest "
            f"effective throughput per routed cell area "
            f"for this dense workload "
            f"({value:.3f} GOPS/mm^2)."
        )

    energy = float(
        winner[
            "vectorless_energy_proxy_mj"
        ]
    )

    return (
        f"{winner['array']} has the lowest "
        f"vectorless-energy proxy for this projection "
        f"({energy:.6f} mJ). "
        f"This is derived from ORFS vectorless power "
        f"and projected compute latency; it is not "
        f"workload-measured energy."
    )


def build_result(
    model,
    scenario,
    objective,
):
    report = load_json(
        REPORT_PATH
    )

    projection = load_json(
        PROJECTION_PATH
    )

    if report.get("status") != "PASS":
        raise SystemExit(
            "ACCELCLOSURE_ADVISOR_ERROR: "
            + "final benchmark report is not PASS"
        )

    if (
        projection.get("schema")
        != "accelclosure.real_model_projection.v1"
    ):
        raise SystemExit(
            "ACCELCLOSURE_ADVISOR_ERROR: "
            + "unsupported projection schema"
        )

    rows = find_rows(
        projection,
        model,
        scenario,
    )

    winner = choose(
        rows,
        objective,
    )

    candidates = []

    for item in sorted(
        rows,
        key=lambda row:
            int(
                row["array_n"]
            ),
    ):
        candidates.append(
            {
                "array":
                    item["array"],

                "target_frequency_mhz":
                    float(
                        item[
                            "target_frequency_mhz"
                        ]
                    ),

                "postroute_fmax_estimate_mhz":
                    float(
                        item[
                            "postroute_fmax_estimate_mhz"
                        ]
                    ),

                "compute_utilization_percent":
                    100.0
                    * float(
                        item[
                            "compute_utilization"
                        ]
                    ),

                "projected_compute_latency_us":
                    float(
                        item[
                            "projected_compute_latency_us_at_target"
                        ]
                    ),

                "effective_gops":
                    float(
                        item[
                            "effective_gops_at_target"
                        ]
                    ),

                "effective_gops_per_mm2":
                    float(
                        item[
                            "effective_gops_per_mm2"
                        ]
                    ),

                "routed_area_mm2":
                    float(
                        item[
                            "routed_area_mm2"
                        ]
                    ),

                "vectorless_power_w":
                    float(
                        item[
                            "vectorless_power_w"
                        ]
                    ),

                "vectorless_energy_proxy_mj":
                    float(
                        item[
                            "vectorless_energy_proxy_mj"
                        ]
                    ),
            }
        )

    return {
        "schema":
            "accelclosure.workload_recommendation.v1",

        "status":
            "PASS",

        "request": {
            "model":
                model,

            "scenario":
                scenario,

            "objective":
                objective,
        },

        "recommendation": {
            "array":
                winner["array"],

            "reason":
                explain(
                    rows,
                    winner,
                    objective,
                    scenario,
                ),
        },

        "candidates":
            candidates,

        "evidence": {
            "benchmark_report":
                REPORT_PATH
                .relative_to(ROOT)
                .as_posix(),

            "projection_results":
                PROJECTION_PATH
                .relative_to(ROOT)
                .as_posix(),

            "hardware_scope":
                (
                    "physically closed Sky130HD "
                    "INT8 weight-stationary arrays"
                ),

            "latency_scope":
                (
                    "analytical compute-core "
                    "projection"
                ),

            "power_scope":
                (
                    "ORFS vectorless estimate"
                ),

            "full_model_rtl_inference":
                False,

            "foundry_signoff":
                False,
        },
    }


def print_human(result):
    request = result["request"]

    recommendation = result[
        "recommendation"
    ]

    print()
    print(
        "============================================================"
    )
    print(
        " ACCELCLOSURE WORKLOAD ADVISOR"
    )
    print(
        "============================================================"
    )

    print()
    print(
        "Model       : "
        + request["model"]
    )

    print(
        "Scenario    : "
        + request["scenario"]
    )

    print(
        "Objective   : "
        + request["objective"]
    )

    print()
    print(
        "Physically Closed Candidates"
    )

    print(
        "-" * 92
    )

    print(
        "Array     Util.      Latency(us)    GOPS/mm2    "
        "Area(mm2)     Power(W)    EnergyProxy(mJ)"
    )

    print(
        "-" * 92
    )

    for item in result["candidates"]:
        print(
            f"{item['array']:<8}"
            f"{item['compute_utilization_percent']:>7.2f}%"
            f"{item['projected_compute_latency_us']:>15.3f}"
            f"{item['effective_gops_per_mm2']:>12.3f}"
            f"{item['routed_area_mm2']:>13.6f}"
            f"{item['vectorless_power_w']:>13.4f}"
            f"{item['vectorless_energy_proxy_mj']:>19.6f}"
        )

    print()
    print(
        "RECOMMENDED = "
        + recommendation["array"]
    )

    print()
    print(
        "Why:"
    )

    print(
        "  "
        + recommendation["reason"]
    )

    print()
    print(
        "Evidence discipline:"
    )

    print(
        "  Latency = compute-core projection."
    )

    print(
        "  Power/energy = vectorless estimate/proxy."
    )

    print(
        "  GDS != foundry signoff."
    )

    print()
    print(
        "WORKLOAD_RECOMMENDATION=PASS"
    )


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Evidence-backed workload advisor "
            "for physically closed AccelClosure designs."
        )
    )

    parser.add_argument(
        "--model",
        required=True,
        help=(
            "tinybert, tinyllama, qwen"
        ),
    )

    parser.add_argument(
        "--scenario",
        required=True,
        help=(
            "encoder, prefill, or decode"
        ),
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

    parser.add_argument(
        "--json",
        action="store_true",
    )

    parser.add_argument(
        "--output",
    )

    args = parser.parse_args()

    model = canonical_model(
        args.model
    )

    scenario = canonical_scenario(
        model,
        args.scenario,
    )

    result = build_result(
        model,
        scenario,
        args.objective,
    )

    if args.output:
        output = Path(
            args.output
        )

        if not output.is_absolute():
            output = (
                ROOT
                / output
            )

        output.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        output.write_text(
            json.dumps(
                result,
                indent=2,
            )
            + "\n"
        )

    if args.json:
        print(
            json.dumps(
                result,
                indent=2,
            )
        )
    else:
        print_human(
            result
        )


if __name__ == "__main__":
    main()
