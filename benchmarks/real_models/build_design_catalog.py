#!/usr/bin/env python3

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

OUT = (
    ROOT
    / "results"
    / "benchmarks"
    / "real_models"
    / "design_catalog.json"
)


N4_PATH = (
    ROOT
    / "results"
    / "runs"
    / "ws_n4_sky130hd_180mhz_20260908T060310Z_c0a64d4b"
    / "eda"
    / "physical"
    / "summary_v2.json"
)

N8_PATH = (
    ROOT
    / "results"
    / "runs"
    / "ws_n8_sky130hd_200mhz_20260906T161925Z_2ff41a10"
    / "closure"
    / "iter1"
    / "eda"
    / "physical"
    / "summary_v2.json"
)

N16_PATH = (
    ROOT
    / "results"
    / "closure"
    / "final_150mhz_closed"
    / "summary.json"
)


def load(path):
    if not path.exists():
        raise FileNotFoundError(path)

    return json.loads(
        path.read_text()
    )


def modern_record(n, path):
    data = load(path)

    if (
        data["schema"]
        != "accelclosure.postroute_summary.v2"
    ):
        raise RuntimeError(
            f"N{n}: wrong summary schema"
        )

    if (
        data["status"]
        != "POST_ROUTE_PHYSICALLY_CLOSED"
    ):
        raise RuntimeError(
            f"N{n}: design is not physically closed"
        )

    timing = data["timing"]
    area = data["area"]
    checks = data["physical_checks"]
    power = data["power"]
    gds = data["artifacts"]["gds"]

    if timing["target_met"] is not True:
        raise RuntimeError(
            f"N{n}: timing target not met"
        )

    if timing["setup_violation_count"] != 0:
        raise RuntimeError(
            f"N{n}: setup violations"
        )

    if timing["hold_violation_count"] != 0:
        raise RuntimeError(
            f"N{n}: hold violations"
        )

    if (
        checks[
            "openroad_route_drc_violations"
        ]
        != 0
    ):
        raise RuntimeError(
            f"N{n}: route violations"
        )

    if (
        checks["antenna_net_violations"] != 0
        or checks["antenna_pin_violations"] != 0
    ):
        raise RuntimeError(
            f"N{n}: antenna violations"
        )

    if (
        power["analysis_type"]
        != "vectorless_estimate"
    ):
        raise RuntimeError(
            f"N{n}: unexpected power method"
        )

    return {
        "array_n": n,
        "array": f"{n}x{n}",
        "dataflow": "weight_stationary",
        "precision": {
            "activation": "INT8",
            "weight": "INT8",
            "accumulator": "INT32"
        },
        "technology": data["target"]["technology"],
        "target_frequency_mhz":
            data["target"]["frequency_mhz"],
        "postroute_fmax_estimate_mhz":
            timing["fmax_estimate_mhz"],
        "worst_setup_slack_ns":
            timing["worst_setup_slack_ns"],
        "setup_violations":
            timing["setup_violation_count"],
        "hold_violations":
            timing["hold_violation_count"],
        "routed_area_mm2":
            area["routed_cell_area_mm2"],
        "utilization_percent":
            area["utilization_percent"],
        "vectorless_power_w":
            power["total_w"],
        "power_method":
            power["analysis_type"],
        "power_workload_measured":
            power["workload_measured"],
        "route_drc_violations":
            checks[
                "openroad_route_drc_violations"
            ],
        "antenna_net_violations":
            checks["antenna_net_violations"],
        "antenna_pin_violations":
            checks["antenna_pin_violations"],
        "gds_sha256":
            gds["sha256"],
        "evidence_source":
            path.relative_to(ROOT).as_posix(),
        "evidence_generation":
            "run_local_postroute_v2"
    }


def legacy_n16_record(path):
    data = load(path)

    if (
        data["closure_status"]
        != "POST_ROUTE_150MHZ_TIMING_CLOSED"
    ):
        raise RuntimeError(
            "N16: legacy design is not closed"
        )

    post = data["post_route"]
    power = data["power"]

    if post["target_met"] is not True:
        raise RuntimeError(
            "N16: timing target not met"
        )

    if post["setup_violation_count"] != 0:
        raise RuntimeError(
            "N16: setup violations"
        )

    if post["hold_violation_count"] != 0:
        raise RuntimeError(
            "N16: hold violations"
        )

    if post["route_drc_violations"] != 0:
        raise RuntimeError(
            "N16: route violations"
        )

    if post["antenna_violations"] != 0:
        raise RuntimeError(
            "N16: antenna violations"
        )

    if (
        power["method"]
        != "ORFS final vectorless estimate"
    ):
        raise RuntimeError(
            "N16: unexpected power method"
        )

    return {
        "array_n": 16,
        "array": "16x16",
        "dataflow":
            data["architecture"]["dataflow"],
        "precision": {
            "activation":
                data["architecture"][
                    "activation_precision"
                ],
            "weight":
                data["architecture"][
                    "weight_precision"
                ],
            "accumulator":
                data["architecture"][
                    "accumulator_precision"
                ]
        },
        "technology":
            data["technology"]["platform"],
        "target_frequency_mhz":
            data["target"]["frequency_mhz"],
        "postroute_fmax_estimate_mhz":
            post["estimated_fmax_mhz"],
        "worst_setup_slack_ns":
            post["worst_setup_slack_ns"],
        "setup_violations":
            post["setup_violation_count"],
        "hold_violations":
            post["hold_violation_count"],
        "routed_area_mm2":
            post["design_area_mm2"],
        "utilization_percent":
            post["utilization_percent"],
        "vectorless_power_w":
            power["estimated_total_w"],
        "power_method":
            "vectorless_estimate",
        "power_workload_measured":
            power[
                "workload_activity_annotated"
            ],
        "route_drc_violations":
            post["route_drc_violations"],
        "antenna_net_violations":
            post["antenna_violations"],
        "antenna_pin_violations":
            post["antenna_violations"],
        "gds_sha256":
            data["gds"]["sha256"],
        "evidence_source":
            path.relative_to(ROOT).as_posix(),
        "evidence_generation":
            "legacy_closed_reference"
    }


records = [
    modern_record(
        4,
        N4_PATH
    ),
    modern_record(
        8,
        N8_PATH
    ),
    legacy_n16_record(
        N16_PATH
    )
]


catalog = {
    "schema":
        "accelclosure.real_model_design_catalog.v2",
    "benchmark_scope": {
        "power":
            "ORFS vectorless estimates only",
        "performance":
            "closed requested clock primary; "
            "post-route Fmax estimate secondary",
        "foundry_signoff":
            False,
        "power_is_workload_measured":
            False
    },
    "designs":
        records
}


OUT.parent.mkdir(
    parents=True,
    exist_ok=True
)

OUT.write_text(
    json.dumps(
        catalog,
        indent=2
    )
    + "\n"
)


print("DESIGN_CATALOG_GATE=PASS")

for record in records:
    print()
    print(
        "ARRAY="
        + record["array"]
    )
    print(
        "TARGET_MHZ="
        + str(
            record[
                "target_frequency_mhz"
            ]
        )
    )
    print(
        "FMAX_ESTIMATE_MHZ="
        + str(
            record[
                "postroute_fmax_estimate_mhz"
            ]
        )
    )
    print(
        "AREA_MM2="
        + str(
            record[
                "routed_area_mm2"
            ]
        )
    )
    print(
        "VECTORLESS_POWER_W="
        + str(
            record[
                "vectorless_power_w"
            ]
        )
    )
    print(
        "SETUP_VIOLATIONS="
        + str(
            record[
                "setup_violations"
            ]
        )
    )
    print(
        "HOLD_VIOLATIONS="
        + str(
            record[
                "hold_violations"
            ]
        )
    )
    print(
        "GDS_SHA256="
        + record[
            "gds_sha256"
        ]
    )

print()
print(
    "CATALOG="
    + OUT.relative_to(
        ROOT
    ).as_posix()
)
