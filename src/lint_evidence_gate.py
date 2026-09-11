#!/usr/bin/env python3

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def resolve(text):
    p = Path(text)
    if not p.is_absolute():
        p = ROOT / p
    return p.resolve()


def require(cond, msg):
    if not cond:
        raise SystemExit(
            "LINT_EVIDENCE_GATE_FAIL: " + msg
        )


def numeric_value(data, names):

    for name in names:

        if name not in data:
            continue

        value = data[name]

        if isinstance(value, bool):
            continue

        if isinstance(value, int):
            return value

        if isinstance(value, list):
            return len(value)

    return None


def find_status(data):

    for key in (
        "status",
        "result",
        "lint_status",
    ):
        value = data.get(key)

        if isinstance(value, str):
            return value.upper()

    return None


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--implementation-context",
        required=True,
    )

    args = parser.parse_args()

    impl_path = resolve(
        args.implementation_context
    )

    require(
        impl_path.exists(),
        f"implementation context missing: {impl_path}",
    )

    impl = json.loads(
        impl_path.read_text()
    )

    info = (
        impl["implementation"]
        ["verification"]
        ["lint_report"]
    )

    require(
        info is not None,
        "lint report is missing",
    )

    lint_path = resolve(
        info["path"]
    )

    require(
        lint_path.exists(),
        f"lint report not found: {lint_path}",
    )

    report = json.loads(
        lint_path.read_text()
    )

    status = find_status(report)

    warnings = numeric_value(
        report,
        (
            "warnings",
            "warning_count",
            "warnings_count",
            "lint_warnings",
        ),
    )

    errors = numeric_value(
        report,
        (
            "errors",
            "error_count",
            "errors_count",
            "lint_errors",
        ),
    )

    # Known parametric-lint reports may place counts
    # under a result/summary object.
    for section_name in (
        "summary",
        "result",
        "verilator",
    ):

        section = report.get(section_name)

        if not isinstance(section, dict):
            continue

        if status is None:
            status = find_status(section)

        if warnings is None:
            warnings = numeric_value(
                section,
                (
                    "warnings",
                    "warning_count",
                    "warnings_count",
                    "lint_warnings",
                ),
            )

        if errors is None:
            errors = numeric_value(
                section,
                (
                    "errors",
                    "error_count",
                    "errors_count",
                    "lint_errors",
                ),
            )

    require(
        status == "PASS",
        f"lint status is not PASS: {status}",
    )

    require(
        warnings is not None,
        "unable to prove lint warning count",
    )

    require(
        errors is not None,
        "unable to prove lint error count",
    )

    require(
        warnings == 0,
        f"lint warnings = {warnings}",
    )

    require(
        errors == 0,
        f"lint errors = {errors}",
    )

    print("LINT_EVIDENCE_GATE=PASS")
    print("LINT_STATUS=PASS")
    print("LINT_WARNINGS=0")
    print("LINT_ERRORS=0")
    print(
        "LINT_REPORT="
        + str(
            lint_path.relative_to(ROOT)
        )
    )


if __name__ == "__main__":
    main()
