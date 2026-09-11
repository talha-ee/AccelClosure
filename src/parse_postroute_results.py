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


def require(cond, message):
    if not cond:
        raise SystemExit(
            "POSTROUTE_PARSE_ERROR: " + message
        )


def number(pattern, text, name):
    m = re.search(
        pattern,
        text,
        re.MULTILINE | re.IGNORECASE,
    )

    require(
        m is not None,
        f"could not find {name}",
    )

    return float(m.group(1))


def integer(pattern, text, name):
    m = re.search(
        pattern,
        text,
        re.MULTILINE | re.IGNORECASE,
    )

    require(
        m is not None,
        f"could not find {name}",
    )

    return int(m.group(1))


def last_integer(patterns, text):

    values = []

    for pattern in patterns:

        for m in re.finditer(
            pattern,
            text,
            re.MULTILINE | re.IGNORECASE,
        ):
            values.append(
                int(m.group(1))
            )

    if not values:
        return None

    return values[-1]


def parse_power(text):

    if not text:
        return None

    matches = list(
        re.finditer(
            r"^Total\s+"
            r"([0-9.eE+\-]+)\s+"
            r"([0-9.eE+\-]+)\s+"
            r"([0-9.eE+\-]+)\s+"
            r"([0-9.eE+\-]+)\s+"
            r"100\.0%",
            text,
            re.MULTILINE,
        )
    )

    if not matches:
        return None

    m = matches[-1]

    return {
        "analysis_type":
            "vectorless_estimate",

        "internal_w":
            float(m.group(1)),

        "switching_w":
            float(m.group(2)),

        "leakage_w":
            float(m.group(3)),

        "total_w":
            float(m.group(4)),

        "workload_measured":
            False,
    }


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--implementation-context",
        required=True,
    )

    parser.add_argument(
        "--finish-report",
        required=True,
    )

    parser.add_argument(
        "--route-evidence",
        required=True,
    )

    parser.add_argument(
        "--antenna-log",
        required=True,
    )

    parser.add_argument(
        "--gds",
        required=True,
    )

    parser.add_argument(
        "--odb",
        required=True,
    )

    parser.add_argument(
        "--sdc",
        required=True,
    )

    parser.add_argument(
        "--power-log",
    )

    parser.add_argument(
        "--output",
        required=True,
    )

    args = parser.parse_args()

    impl_path = resolve(
        args.implementation_context
    )

    finish_path = resolve(
        args.finish_report
    )

    route_path = resolve(
        args.route_evidence
    )

    antenna_path = resolve(
        args.antenna_log
    )

    gds_path = resolve(
        args.gds
    )

    odb_path = resolve(
        args.odb
    )

    sdc_path = resolve(
        args.sdc
    )

    out_path = resolve(
        args.output
    )

    require(
        impl_path.exists(),
        "implementation context missing",
    )

    require(
        finish_path.exists(),
        "6_finish.rpt missing",
    )

    require(
        route_path.exists(),
        "route evidence missing",
    )

    require(
        antenna_path.exists(),
        "antenna log missing",
    )

    require(
        gds_path.exists(),
        "final GDS missing",
    )

    require(
        odb_path.exists(),
        "final ODB missing",
    )

    require(
        sdc_path.exists(),
        "final SDC missing",
    )

    require(
        not out_path.exists(),
        f"refusing overwrite: {out_path}",
    )

    impl = json.loads(
        impl_path.read_text()
    )

    finish = finish_path.read_text(
        errors="replace"
    )

    route = route_path.read_text(
        errors="replace"
    )

    antenna = antenna_path.read_text(
        errors="replace"
    )

    power_text = ""

    power_path = None

    if args.power_log:

        power_path = resolve(
            args.power_log
        )

        if power_path.exists():

            power_text = power_path.read_text(
                errors="replace"
            )

    # --------------------------------------------------------
    # Official ORFS final timing.
    # --------------------------------------------------------

    tns = number(
        r"tns max\s+(-?[0-9.]+)",
        finish,
        "TNS",
    )

    wns = number(
        r"wns max\s+(-?[0-9.]+)",
        finish,
        "WNS",
    )

    worst_slack = number(
        r"worst slack max\s+(-?[0-9.]+)",
        finish,
        "worst setup slack",
    )

    period_match = re.search(
        r"period_min\s*=\s*([0-9.]+)"
        r"\s+fmax\s*=\s*([0-9.]+)",
        finish,
        re.IGNORECASE,
    )

    require(
        period_match is not None,
        "minimum period/Fmax missing",
    )

    minimum_period = float(
        period_match.group(1)
    )

    fmax = float(
        period_match.group(2)
    )

    setup_violations = integer(
        r"setup violation count\s+(\d+)",
        finish,
        "setup violation count",
    )

    hold_violations = integer(
        r"hold violation count\s+(\d+)",
        finish,
        "hold violation count",
    )

    # --------------------------------------------------------
    # Final routed cell area.
    #
    # ORFS versions differ in where report_design_area appears.
    # Prefer 6_finish.rpt when present; otherwise use the
    # explicitly generated final power/area report.
    # --------------------------------------------------------

    area_source = None

    area_match = re.search(
        r"Design area\s+([0-9.]+)\s+um\^2"
        r"\s+([0-9.]+)% utilization",
        finish,
        re.IGNORECASE,
    )

    if area_match is not None:
        area_source = "ORFS 6_finish.rpt"

    elif power_text:

        area_match = re.search(
            r"Design area\s+([0-9.]+)\s+um\^2"
            r"\s+([0-9.]+)% utilization",
            power_text,
            re.IGNORECASE,
        )

        if area_match is not None:
            area_source = "final_power.log report_design_area"

    require(
        area_match is not None,
        "final routed area/utilization missing "
        "from both finish report and power log",
    )

    area_um2 = float(
        area_match.group(1)
    )

    utilization = float(
        area_match.group(2)
    )

    # --------------------------------------------------------
    # Route DRC evidence.
    #
    # Use final/last violation count when multiple detail-route
    # optimization iterations are present.
    # --------------------------------------------------------

    route_drc = last_integer(
        (
            r"Number of violations\s*=\s*(\d+)",
            r"violation count\s*[:=]?\s*(\d+)",
            r"violations\s*=\s*(\d+)",
        ),
        route,
    )

    # --------------------------------------------------------
    # Antenna evidence.
    # --------------------------------------------------------

    antenna_net = last_integer(
        (
            r"Found\s+(\d+)\s+net violations",
        ),
        antenna,
    )

    antenna_pin = last_integer(
        (
            r"Found\s+(\d+)\s+pin violations",
        ),
        antenna,
    )

    timing_closed = (
        worst_slack >= 0.0
        and tns >= -1e-9
        and setup_violations == 0
        and hold_violations == 0
        and minimum_period
            <= float(
                impl["request"][
                    "target_period_ns"
                ]
            )
    )

    route_clean = (
        route_drc == 0
        if route_drc is not None
        else False
    )

    antenna_clean = (
        antenna_net == 0
        and antenna_pin == 0
        if (
            antenna_net is not None
            and antenna_pin is not None
        )
        else False
    )

    power = parse_power(
        power_text
    )

    if not timing_closed:

        status = "POST_ROUTE_TIMING_FAILED"

    elif (
        route_drc is None
        or antenna_net is None
        or antenna_pin is None
    ):

        status = "PHYSICAL_EVIDENCE_INCOMPLETE"

    elif not route_clean:

        status = "ROUTING_DRC_FAILED"

    elif not antenna_clean:

        status = "ANTENNA_CHECK_FAILED"

    else:

        status = "POST_ROUTE_PHYSICALLY_CLOSED"

    record = {
        "schema":
            "accelclosure.postroute_summary.v2",

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

        "target": {
            "technology":
                impl["request"]["technology"],

            "frequency_mhz":
                impl["request"][
                    "target_frequency_mhz"
                ],

            "period_ns":
                impl["request"][
                    "target_period_ns"
                ],
        },

        "timing": {
            "source":
                "ORFS final extracted post-route report",

            "worst_setup_slack_ns":
                worst_slack,

            "wns_ns":
                wns,

            "tns_ns":
                tns,

            "minimum_period_ns":
                minimum_period,

            "fmax_estimate_mhz":
                fmax,

            "setup_violation_count":
                setup_violations,

            "hold_violation_count":
                hold_violations,

            "target_met":
                timing_closed,
        },

        "area": {
            "source":
                area_source,

            "routed_cell_area_um2":
                area_um2,

            "routed_cell_area_mm2":
                area_um2 / 1_000_000.0,

            "utilization_percent":
                utilization,
        },

        "physical_checks": {
            "openroad_route_drc_violations":
                route_drc,

            "antenna_net_violations":
                antenna_net,

            "antenna_pin_violations":
                antenna_pin,

            "route_clean":
                route_clean,

            "antenna_clean":
                antenna_clean,

            "foundry_signoff_drc_lvs":
                False,
        },

        "power":
            power,

        "artifacts": {
            "gds": {
                "path":
                    str(
                        gds_path.relative_to(ROOT)
                    ),

                "size_bytes":
                    gds_path.stat().st_size,

                "sha256":
                    sha256(gds_path),
            },

            "odb": {
                "path":
                    str(
                        odb_path.relative_to(ROOT)
                    ),

                "size_bytes":
                    odb_path.stat().st_size,

                "sha256":
                    sha256(odb_path),
            },

            "sdc": {
                "path":
                    str(
                        sdc_path.relative_to(ROOT)
                    ),

                "size_bytes":
                    sdc_path.stat().st_size,

                "sha256":
                    sha256(sdc_path),
            },
        },

        "status":
            status,

        "claim_discipline": {
            "fmax_is_sta_estimate":
                True,

            "power_is_vectorless_estimate":
                power is not None,

            "gds_is_not_tapeout_signoff":
                True,

            "openroad_drc_is_not_foundry_signoff":
                True,
        },

        "provenance": {
            "implementation_context_sha256":
                sha256(impl_path),

            "finish_report_sha256":
                sha256(finish_path),

            "route_evidence_sha256":
                sha256(route_path),

            "antenna_log_sha256":
                sha256(antenna_path),

            "power_log_sha256":
                (
                    sha256(power_path)
                    if (
                        power_path
                        and power_path.exists()
                    )
                    else None
                ),
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

    print("POSTROUTE_SUMMARY_WRITTEN")
    print("STATUS=" + status)

    print(
        "TIMING_TARGET_MET="
        + str(timing_closed).lower()
    )

    print(
        "WORST_SETUP_SLACK_NS="
        + str(worst_slack)
    )

    print(
        "FMAX_ESTIMATE_MHZ="
        + str(fmax)
    )

    print(
        "ROUTED_AREA_MM2="
        + str(
            area_um2 / 1_000_000.0
        )
    )

    print(
        "ROUTE_DRC_VIOLATIONS="
        + str(route_drc)
    )

    print(
        "ANTENNA_NET_VIOLATIONS="
        + str(antenna_net)
    )

    print(
        "ANTENNA_PIN_VIOLATIONS="
        + str(antenna_pin)
    )

    if power:

        print(
            "VECTORLESS_POWER_W="
            + str(
                power["total_w"]
            )
        )

    print(
        "GDS_SHA256="
        + record["artifacts"]["gds"]["sha256"]
    )


if __name__ == "__main__":
    main()
