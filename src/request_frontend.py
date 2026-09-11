#!/usr/bin/env python3

import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

FAMILY_PATH = (
    ROOT
    / "configs/product/accelerator_family.json"
)


class RequestError(Exception):
    pass


def load_family():
    return json.loads(
        FAMILY_PATH.read_text()
    )


def extract_dimension(prompt):
    patterns = [
        r"\b(\d+)\s*[xX×]\s*(\d+)\b",
        r"\b(\d+)\s+by\s+(\d+)\b"
    ]

    for pattern in patterns:
        match = re.search(
            pattern,
            prompt,
            re.IGNORECASE
        )

        if match:
            rows = int(match.group(1))
            cols = int(match.group(2))

            return rows, cols

    return None


def extract_frequency(prompt):
    match = re.search(
        r"\b(?:at|>=?|at\s+least|target(?:ing)?)?\s*"
        r"(\d+(?:\.\d+)?)\s*MHz\b",
        prompt,
        re.IGNORECASE
    )

    if not match:
        return None

    return float(match.group(1))


def extract_dataflow(prompt):
    p = prompt.lower()

    if (
        "weight-stationary" in p
        or "weight stationary" in p
        or re.search(r"\bws\b", p)
    ):
        return "weight_stationary"

    if (
        "output-stationary" in p
        or "output stationary" in p
        or re.search(r"\bos\b", p)
    ):
        return "output_stationary"

    if (
        "input-stationary" in p
        or "input stationary" in p
        or re.search(r"\bis\b", p)
    ):
        return "input_stationary"

    return None


def extract_technology(prompt):
    p = prompt.lower()

    if "sky130" in p:
        return "sky130hd"

    return None


def extract_objective(prompt):
    p = prompt.lower()

    if (
        "minimum area" in p
        or "minimize area" in p
        or "area optimized" in p
    ):
        return "area"

    if (
        "maximum frequency" in p
        or "maximize frequency" in p
        or "timing optimized" in p
        or "high performance" in p
    ):
        return "timing"

    if (
        "ppa" in p
        or "balanced" in p
        or "energy efficient" in p
    ):
        return "balanced_ppa"

    return "timing"


def is_power_of_two(value):
    return (
        value >= 1
        and (value & (value - 1)) == 0
    )


def build_request(prompt):
    family = load_family()

    dimension = extract_dimension(prompt)

    if dimension is None:
        raise RequestError(
            "Array dimension was not found. "
            "Example: 8x8 or 16x16."
        )

    rows, cols = dimension

    if rows != cols:
        raise RequestError(
            "AccelClosure v1 currently supports "
            "square systolic arrays."
        )

    minimum_n = family["array"]["minimum_n"]

    if rows < minimum_n:
        raise RequestError(
            f"Array dimension must be >= {minimum_n}."
        )

    if (
        family["array"]["power_of_two_required"]
        and not is_power_of_two(rows)
    ):
        raise RequestError(
            "AccelClosure v1 currently requires "
            "power-of-two array dimensions."
        )

    frequency = extract_frequency(prompt)

    if frequency is None:
        raise RequestError(
            "Target frequency was not found. "
            "Example: 150 MHz."
        )

    dataflow = (
        extract_dataflow(prompt)
        or "weight_stationary"
    )

    dataflow_info = family["dataflows"].get(
        dataflow
    )

    if (
        dataflow_info is None
        or not dataflow_info["supported"]
    ):
        raise RequestError(
            f"Requested dataflow '{dataflow}' "
            "is not implemented in AccelClosure v1."
        )

    technology = (
        extract_technology(prompt)
        or "sky130hd"
    )

    if technology not in family["technology"]:
        raise RequestError(
            f"Technology '{technology}' "
            "is not currently supported."
        )

    request = {
        "schema":
            "accelclosure.design_request.v1",

        "original_prompt":
            prompt,

        "architecture": {
            "family":
                "systolic_array",

            "rows":
                rows,

            "cols":
                cols,

            "n":
                rows,

            "dataflow":
                dataflow
        },

        "arithmetic": {
            "activation":
                "INT8",

            "weight":
                "INT8",

            "accumulator":
                "INT32"
        },

        "technology":
            technology,

        "target": {
            "frequency_mhz":
                frequency,

            "period_ns":
                round(
                    1000.0 / frequency,
                    6
                )
        },

        "optimization_objective":
            extract_objective(prompt),

        "result_reuse_allowed":
            False,

        "requires_new_verification":
            True,

        "requires_new_eda_measurement":
            True
    }

    return request


def main():
    if len(sys.argv) < 2:
        print(
            'usage: request_frontend.py '
            '"<accelerator request>"'
        )

        return 2

    prompt = " ".join(sys.argv[1:])

    try:
        request = build_request(prompt)

    except RequestError as exc:
        print(
            f"REQUEST_REJECTED: {exc}",
            file=sys.stderr
        )

        return 1

    print(
        json.dumps(
            request,
            indent=2
        )
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
