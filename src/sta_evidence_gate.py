#!/usr/bin/env python3

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

SUPPORTED_SCHEMAS = {
    "accelclosure.prelayout_sta_summary.v1",
    "accelclosure.prelayout_sta_summary.v2",
}


def resolve(text):
    p = Path(text)

    if not p.is_absolute():
        p = ROOT / p

    return p.resolve()


def fail(message, code=1):
    print(
        "STA_EVIDENCE_GATE_FAIL: "
        + message
    )
    raise SystemExit(code)


def load(path):
    if not path.exists():
        fail(
            f"file does not exist: {path}"
        )

    return json.loads(
        path.read_text()
    )


def normalize(summary):

    schema = summary.get("schema")

    if schema not in SUPPORTED_SCHEMAS:
        fail(
            f"unsupported STA schema: {schema}"
        )

    # --------------------------------------------------------
    # v1 historical representation
    # --------------------------------------------------------

    if schema == "accelclosure.prelayout_sta_summary.v1":

        measurement = summary.get(
            "measurement"
        )

        closure = summary.get(
            "closure"
        )

        if not isinstance(measurement, dict):
            fail(
                "v1 measurement block missing"
            )

        if not isinstance(closure, dict):
            fail(
                "v1 closure block missing"
            )

        status = closure.get(
            "status"
        )

        explicit_target_met = closure.get(
            "target_met"
        )

    # --------------------------------------------------------
    # v2 canonical product representation
    # --------------------------------------------------------

    else:

        measurement = summary.get(
            "measured"
        )

        if not isinstance(measurement, dict):
            fail(
                "v2 measured block missing"
            )

        status = summary.get(
            "status"
        )

        explicit_target_met = summary.get(
            "target_met"
        )

    target = summary.get(
        "target"
    )

    if not isinstance(target, dict):
        fail(
            "target block missing"
        )

    required_measurements = (
        "worst_setup_slack_ns",
        "tns_ns",
        "minimum_period_ns",
        "fmax_estimate_mhz",
    )

    for key in required_measurements:

        if key not in measurement:
            fail(
                f"measurement missing: {key}"
            )

    if "frequency_mhz" not in target:
        fail(
            "target frequency missing"
        )

    if "period_ns" not in target:
        fail(
            "target period missing"
        )

    worst_slack = float(
        measurement[
            "worst_setup_slack_ns"
        ]
    )

    tns = float(
        measurement[
            "tns_ns"
        ]
    )

    minimum_period = float(
        measurement[
            "minimum_period_ns"
        ]
    )

    fmax = float(
        measurement[
            "fmax_estimate_mhz"
        ]
    )

    target_frequency = float(
        target["frequency_mhz"]
    )

    target_period = float(
        target["period_ns"]
    )

    # Independent evidence-based derivation.
    derived_target_met = (
        worst_slack >= 0.0
        and tns >= -1e-9
        and minimum_period <= target_period + 1e-9
    )

    if explicit_target_met is None:
        fail(
            "explicit target_met evidence missing"
        )

    if bool(explicit_target_met) != derived_target_met:
        fail(
            "explicit target_met conflicts "
            "with measured timing evidence"
        )

    expected_status = (
        "POST_SYNTH_TIMING_CLOSED"
        if derived_target_met
        else "TIMING_FAILED"
    )

    if status != expected_status:
        fail(
            f"status '{status}' conflicts with "
            f"measured result '{expected_status}'"
        )

    return {
        "schema":
            schema,

        "status":
            status,

        "target_met":
            derived_target_met,

        "target_frequency_mhz":
            target_frequency,

        "target_period_ns":
            target_period,

        "worst_setup_slack_ns":
            worst_slack,

        "tns_ns":
            tns,

        "minimum_period_ns":
            minimum_period,

        "fmax_estimate_mhz":
            fmax,

        "measurement":
            measurement,
    }


def main():

    parser = argparse.ArgumentParser(
        description=(
            "Validate and normalize AccelClosure "
            "pre-layout STA evidence."
        )
    )

    parser.add_argument(
        "--summary",
        required=True,
    )

    parser.add_argument(
        "--implementation-context",
        required=True,
    )

    parser.add_argument(
        "--require-pass",
        action="store_true",
    )

    args = parser.parse_args()

    summary_path = resolve(
        args.summary
    )

    impl_path = resolve(
        args.implementation_context
    )

    summary = load(
        summary_path
    )

    impl = load(
        impl_path
    )

    evidence = normalize(
        summary
    )

    request = impl.get(
        "request"
    )

    if not isinstance(request, dict):
        fail(
            "implementation request block missing"
        )

    impl_frequency = float(
        request[
            "target_frequency_mhz"
        ]
    )

    impl_period = float(
        request[
            "target_period_ns"
        ]
    )

    # --------------------------------------------------------
    # Cross-file target integrity.
    # --------------------------------------------------------

    if abs(
        evidence[
            "target_frequency_mhz"
        ]
        - impl_frequency
    ) > 1e-6:

        fail(
            "STA frequency does not match "
            "implementation context"
        )

    if abs(
        evidence[
            "target_period_ns"
        ]
        - impl_period
    ) > 1e-6:

        fail(
            "STA period does not match "
            "implementation context"
        )

    print("STA_EVIDENCE_GATE=PASS")

    print(
        "STA_SCHEMA="
        + evidence["schema"]
    )

    print(
        "STATUS="
        + evidence["status"]
    )

    print(
        "TARGET_MET="
        + str(
            evidence["target_met"]
        ).lower()
    )

    print(
        "WORST_SETUP_SLACK_NS="
        + str(
            evidence[
                "worst_setup_slack_ns"
            ]
        )
    )

    print(
        "TNS_NS="
        + str(
            evidence["tns_ns"]
        )
    )

    print(
        "MINIMUM_PERIOD_NS="
        + str(
            evidence[
                "minimum_period_ns"
            ]
        )
    )

    print(
        "FMAX_ESTIMATE_MHZ="
        + str(
            evidence[
                "fmax_estimate_mhz"
            ]
        )
    )

    if (
        args.require_pass
        and not evidence["target_met"]
    ):

        print(
            "PHYSICAL_DESIGN_ALLOWED=false"
        )

        raise SystemExit(10)

    if evidence["target_met"]:

        print(
            "PHYSICAL_DESIGN_ALLOWED=true"
        )

    else:

        print(
            "PHYSICAL_DESIGN_ALLOWED=false"
        )

        # Exit 10 represents measured timing failure,
        # not tool/runtime failure.
        raise SystemExit(10)


if __name__ == "__main__":
    main()
