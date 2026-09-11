#!/usr/bin/env python3

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

CATALOG = (
    ROOT
    / "configs"
    / "product"
    / "reference_catalog.json"
)

PURPOSE_KINDS = {
    "architecture": {
        "GOLDEN_ARCHITECTURE_REFERENCE",
    },
    "closure": {
        "ACCELCLOSURE_CLOSED_REFERENCE",
    },
}


def resolve(text):
    p = Path(text)

    if not p.is_absolute():
        p = ROOT / p

    return p.resolve()


def load_json(path):
    return json.loads(
        path.read_text()
    )


def require(cond, message):
    if not cond:
        raise SystemExit(
            "REFERENCE_REGISTRY_ERROR: "
            + message
        )


def load_catalog():

    data = load_json(
        CATALOG
    )

    require(
        data.get("schema")
        == "accelclosure.reference_catalog.v1",
        "unsupported reference catalog schema",
    )

    return data


def canonical_request(source):

    schema = source.get("schema")

    req = source.get("request")

    require(
        isinstance(req, dict),
        "request block missing",
    )

    # --------------------------------------------------------
    # Run Context v1
    #
    # The original product request is intentionally structured:
    #
    # request.architecture.n
    # request.architecture.dataflow
    # request.technology
    # request.target.frequency_mhz
    # request.target.period_ns
    #
    # parameters contains a normalized duplicate. We use the
    # request as authoritative and cross-check parameters.
    # --------------------------------------------------------

    if schema == "accelclosure.run_context.v1":

        arch = req.get(
            "architecture"
        )

        target = req.get(
            "target"
        )

        require(
            isinstance(arch, dict),
            "run-context architecture block missing",
        )

        require(
            isinstance(target, dict),
            "run-context target block missing",
        )

        require(
            arch.get("n") is not None,
            "run-context request architecture.n missing",
        )

        require(
            arch.get("dataflow") is not None,
            "run-context request architecture.dataflow missing",
        )

        require(
            req.get("technology") is not None,
            "run-context request technology missing",
        )

        require(
            target.get("frequency_mhz") is not None,
            "run-context target frequency missing",
        )

        require(
            target.get("period_ns") is not None,
            "run-context target period missing",
        )

        n = int(
            arch["n"]
        )

        dataflow = arch[
            "dataflow"
        ]

        technology = req[
            "technology"
        ]

        frequency = float(
            target["frequency_mhz"]
        )

        period = float(
            target["period_ns"]
        )

        # Square-array invariant.
        rows = arch.get(
            "rows"
        )

        cols = arch.get(
            "cols"
        )

        if rows is not None:
            require(
                int(rows) == n,
                "run-context rows != n",
            )

        if cols is not None:
            require(
                int(cols) == n,
                "run-context cols != n",
            )

        # Cross-check normalized parameters when present.
        params = source.get(
            "parameters"
        )

        if isinstance(params, dict):

            if params.get("rows") is not None:
                require(
                    int(params["rows"]) == n,
                    "parameters.rows conflicts with request",
                )

            if params.get("cols") is not None:
                require(
                    int(params["cols"]) == n,
                    "parameters.cols conflicts with request",
                )

            if params.get("dataflow") is not None:
                require(
                    params["dataflow"] == dataflow,
                    "parameters.dataflow conflicts with request",
                )

            if params.get("technology") is not None:
                require(
                    params["technology"] == technology,
                    "parameters.technology conflicts with request",
                )

            if params.get(
                "target_frequency_mhz"
            ) is not None:

                require(
                    abs(
                        float(
                            params[
                                "target_frequency_mhz"
                            ]
                        )
                        - frequency
                    ) <= 1e-9,
                    (
                        "parameters target frequency "
                        "conflicts with request"
                    ),
                )

            if params.get(
                "target_period_ns"
            ) is not None:

                require(
                    abs(
                        float(
                            params[
                                "target_period_ns"
                            ]
                        )
                        - period
                    ) <= 1e-9,
                    (
                        "parameters target period "
                        "conflicts with request"
                    ),
                )

    # --------------------------------------------------------
    # Implementation Context v1
    #
    # By this stage the request has already been normalized.
    # --------------------------------------------------------

    elif schema == (
        "accelclosure.implementation_context.v1"
    ):

        require(
            req.get("n") is not None,
            "implementation request n missing",
        )

        require(
            req.get("dataflow") is not None,
            "implementation request dataflow missing",
        )

        require(
            req.get("technology") is not None,
            "implementation request technology missing",
        )

        require(
            req.get(
                "target_frequency_mhz"
            ) is not None,
            "implementation request frequency missing",
        )

        require(
            req.get(
                "target_period_ns"
            ) is not None,
            "implementation request period missing",
        )

        n = int(
            req["n"]
        )

        dataflow = req[
            "dataflow"
        ]

        technology = req[
            "technology"
        ]

        frequency = float(
            req[
                "target_frequency_mhz"
            ]
        )

        period = float(
            req[
                "target_period_ns"
            ]
        )

    else:

        require(
            False,
            (
                "unsupported context schema for "
                f"request normalization: {schema}"
            ),
        )

    # --------------------------------------------------------
    # Universal clock consistency.
    # --------------------------------------------------------

    expected_period = (
        1000.0 / frequency
    )

    require(
        abs(
            period - expected_period
        ) <= 0.001,
        (
            "target frequency/period inconsistency: "
            f"{frequency} MHz vs {period} ns"
        ),
    )

    return {
        "n":
            n,

        "dataflow":
            dataflow,

        "technology":
            technology,

        "target_frequency_mhz":
            frequency,

        "target_period_ns":
            period,
    }


def compatible_architecture(
    ref,
    request,
):

    arch = ref.get(
        "architecture",
        {},
    )

    family = arch.get(
        "family"
    )

    if (
        family is not None
        and family != "systolic_array"
    ):
        return False

    requested_flow = request[
        "dataflow"
    ]

    supported = arch.get(
        "supported_dataflows"
    )

    if supported is not None:

        if requested_flow not in supported:
            return False

    elif arch.get("dataflow"):

        if (
            arch["dataflow"]
            != requested_flow
        ):
            return False

    return True


def score_reference(
    ref,
    request,
    purpose,
):

    if (
        ref.get("kind")
        not in PURPOSE_KINDS[purpose]
    ):
        return -1

    if not compatible_architecture(
        ref,
        request,
    ):
        return -1

    score = 200

    arch = ref.get(
        "architecture",
        {},
    )

    if (
        arch.get("n")
        == request["n"]
    ):
        score += 40

    if (
        arch.get(
            "target_frequency_mhz"
        )
        == request[
            "target_frequency_mhz"
        ]
    ):
        score += 30

    if (
        arch.get("technology")
        == request["technology"]
    ):
        score += 20

    return score


def select(
    catalog,
    request,
    purpose,
    limit,
):

    ranked = []

    for ref in catalog[
        "references"
    ]:

        score = score_reference(
            ref,
            request,
            purpose,
        )

        if score >= 0:
            ranked.append(
                (score, ref)
            )

    ranked.sort(
        key=lambda item: item[0],
        reverse=True,
    )

    return [
        {
            "score":
                score,

            "reference":
                ref,
        }
        for score, ref
        in ranked[:limit]
    ]


def main():

    parser = argparse.ArgumentParser()

    source = parser.add_mutually_exclusive_group(
        required=True
    )

    source.add_argument(
        "--run-context"
    )

    source.add_argument(
        "--implementation-context"
    )

    parser.add_argument(
        "--purpose",
        choices=[
            "architecture",
            "closure",
        ],
        required=True,
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=3,
    )

    parser.add_argument(
        "--output"
    )

    args = parser.parse_args()

    # --------------------------------------------------------
    # Enforce correct lifecycle ordering.
    # --------------------------------------------------------

    if args.purpose == "architecture":

        require(
            args.run_context is not None,
            (
                "architecture selection must use "
                "--run-context before RTL generation"
            ),
        )

        source_path = resolve(
            args.run_context
        )

        expected_schema = (
            "accelclosure.run_context.v1"
        )

        source_kind = "run_context"

    else:

        require(
            args.implementation_context
            is not None,
            (
                "closure selection must use "
                "--implementation-context"
            ),
        )

        source_path = resolve(
            args.implementation_context
        )

        expected_schema = (
            "accelclosure.implementation_context.v1"
        )

        source_kind = (
            "implementation_context"
        )

    require(
        source_path.exists(),
        f"context missing: {source_path}",
    )

    context = load_json(
        source_path
    )

    require(
        context.get("schema")
        == expected_schema,
        (
            "unexpected context schema: "
            f"{context.get('schema')}"
        ),
    )

    request = canonical_request(
        context
    )

    catalog = load_catalog()

    refs = select(
        catalog,
        request,
        args.purpose,
        args.limit,
    )

    result = {
        "schema":
            "accelclosure.reference_selection.v2",

        "purpose":
            args.purpose,

        "source_context": {
            "kind":
                source_kind,

            "path":
                str(
                    source_path.relative_to(ROOT)
                ),
        },

        "run_id":
            context["run_id"],

        "implementation_id":
            context.get(
                "implementation_id"
            ),

        "request":
            request,

        "selection":
            refs,

        "selection_policy": {
            "strict_reference_kind_filter":
                True,

            "metric_reuse_allowed":
                False,

            "fresh_eda_required":
                True,

            "architecture_before_rtl":
                True,

            "closure_after_measured_sta_failure":
                (
                    args.purpose
                    == "closure"
                ),
        },
    }

    text = (
        json.dumps(
            result,
            indent=2,
        )
        + "\n"
    )

    if args.output:

        out = resolve(
            args.output
        )

        require(
            not out.exists(),
            f"refusing overwrite: {out}",
        )

        out.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        out.write_text(
            text
        )

        print(
            "REFERENCE_SELECTION_WRITTEN="
            + str(
                out.relative_to(ROOT)
            )
        )

    else:

        print(
            text,
            end="",
        )


if __name__ == "__main__":
    main()
