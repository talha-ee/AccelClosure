#!/usr/bin/env python3

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def resolve(text):
    p = Path(text)

    if not p.is_absolute():
        p = ROOT / p

    return p.resolve()


def sha256(path):
    h = hashlib.sha256()

    with path.open("rb") as f:
        for block in iter(
            lambda: f.read(1024 * 1024),
            b"",
        ):
            h.update(block)

    return h.hexdigest()


def require(cond, msg):
    if not cond:
        raise SystemExit(
            "STA_PARSE_ERROR: " + msg
        )


def number(pattern, text, name):
    match = re.search(
        pattern,
        text,
        re.MULTILINE,
    )

    require(
        match is not None,
        f"could not find {name}",
    )

    return float(
        match.group(1)
    )


def integer(pattern, text, name):
    match = re.search(
        pattern,
        text,
        re.MULTILINE,
    )

    require(
        match is not None,
        f"could not find {name}",
    )

    return int(
        match.group(1)
    )


def optional_string(pattern, text):

    match = re.search(
        pattern,
        text,
        re.MULTILINE,
    )

    if not match:
        return None

    return match.group(1).strip()


def classify_path(startpoint, endpoint):

    start = startpoint or ""
    end = endpoint or ""

    if (
        start.startswith("act_data_in")
        and "psum_out" in end
    ):
        return (
            "input_activation_to_pe_mac_result_register"
        )

    if (
        start.startswith("act_data_in")
        and "mult_reg" in end
    ):
        return (
            "input_activation_to_multiplier_pipeline_register"
        )

    if (
        "act_out" in start
        and "mult_reg" in end
    ):
        return (
            "registered_activation_to_multiplier_pipeline_register"
        )

    if (
        "weight" in start
        and "mult_reg" in end
    ):
        return (
            "registered_weight_to_multiplier_pipeline_register"
        )

    if start.endswith("(input port"):
        return "input_to_registered_datapath"

    return "unclassified_timing_path"


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--implementation-context",
        required=True,
    )

    parser.add_argument(
        "--log",
        required=True,
    )

    parser.add_argument(
        "--output",
        required=True,
    )

    args = parser.parse_args()

    impl_path = resolve(
        args.implementation_context
    )

    log_path = resolve(
        args.log
    )

    out_path = resolve(
        args.output
    )

    require(
        impl_path.exists(),
        "implementation context missing",
    )

    require(
        log_path.exists(),
        "STA log missing",
    )

    require(
        not out_path.exists(),
        f"refusing overwrite: {out_path}",
    )

    impl = json.loads(
        impl_path.read_text()
    )

    text = log_path.read_text(
        errors="replace"
    )

    require(
        "ACCELCLOSURE_IMPLEMENTATION_STA_COMPLETE"
        in text,
        "STA completion marker missing",
    )

    area_um2 = number(
        r"Design area\s+([0-9.]+)\s+um\^2",
        text,
        "design area",
    )

    instances = integer(
        r"ACCELCLOSURE_INSTANCE_COUNT=(\d+)",
        text,
        "instance count",
    )

    worst_slack = number(
        r"worst slack max\s+(-?[0-9.]+)",
        text,
        "worst slack",
    )

    wns = number(
        r"wns max\s+(-?[0-9.]+)",
        text,
        "WNS",
    )

    tns = number(
        r"tns max\s+(-?[0-9.]+)",
        text,
        "TNS",
    )

    period_match = re.search(
        r"period_min\s*=\s*([0-9.]+)"
        r"\s+fmax\s*=\s*([0-9.]+)",
        text,
    )

    require(
        period_match is not None,
        "minimum period/Fmax not found",
    )

    min_period = float(
        period_match.group(1)
    )

    fmax = float(
        period_match.group(2)
    )

    startpoint = optional_string(
        r"^Startpoint:\s+(.+)$",
        text,
    )

    endpoint = optional_string(
        r"^Endpoint:\s+(.+)$",
        text,
    )

    target = impl["request"]

    target_met = (
        worst_slack >= 0.0
        and tns >= -1e-9
    )

    status = (
        "POST_SYNTH_TIMING_CLOSED"
        if target_met
        else "TIMING_FAILED"
    )

    record = {
        "schema":
            "accelclosure.prelayout_sta_summary.v2",

        "generated_utc":
            datetime.now(
                timezone.utc
            ).isoformat(),

        "run_id":
            impl["run_id"],

        "implementation_id":
            impl["implementation_id"],

        "iteration":
            impl["iteration"],

        "stage":
            "post_synthesis_prelayout_sta",

        "target": {
            "technology":
                target["technology"],

            "frequency_mhz":
                target[
                    "target_frequency_mhz"
                ],

            "period_ns":
                target[
                    "target_period_ns"
                ],
        },

        "measured": {
            "design_area_um2":
                area_um2,

            "design_area_mm2":
                area_um2 / 1_000_000.0,

            "instance_count":
                instances,

            "worst_setup_slack_ns":
                worst_slack,

            "wns_ns":
                wns,

            "tns_ns":
                tns,

            "minimum_period_ns":
                min_period,

            "fmax_estimate_mhz":
                fmax,
        },

        "critical_path": {
            "startpoint":
                startpoint,

            "endpoint":
                endpoint,

            "classification":
                classify_path(
                    startpoint,
                    endpoint,
                ),
        },

        "target_met":
            target_met,

        "status":
            status,

        "physical_design":
            False,

        "post_route":
            False,

        "provenance": {
            "implementation_context": {
                "path":
                    str(
                        impl_path.relative_to(ROOT)
                    ),

                "sha256":
                    sha256(impl_path),
            },

            "sta_log": {
                "path":
                    str(
                        log_path.relative_to(ROOT)
                    ),

                "sha256":
                    sha256(log_path),
            },
        },
    }

    out_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    out_path.write_text(
        json.dumps(
            record,
            indent=2,
        )
        + "\n"
    )

    print("PRELAYOUT_STA_SUMMARY_WRITTEN")
    print("STATUS=" + status)
    print(
        "TARGET_MET="
        + str(target_met).lower()
    )
    print(
        "WORST_SETUP_SLACK_NS="
        + str(worst_slack)
    )
    print(
        "TNS_NS="
        + str(tns)
    )
    print(
        "MINIMUM_PERIOD_NS="
        + str(min_period)
    )
    print(
        "FMAX_ESTIMATE_MHZ="
        + str(fmax)
    )
    print(
        "AREA_MM2="
        + str(area_um2 / 1_000_000.0)
    )
    print(
        "INSTANCE_COUNT="
        + str(instances)
    )


if __name__ == "__main__":
    main()
