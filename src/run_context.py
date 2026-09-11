#!/usr/bin/env python3

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from request_frontend import build_request, RequestError


ROOT = Path(__file__).resolve().parents[1]


def slug(text):
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


def sha256_text(text):
    return hashlib.sha256(
        text.encode("utf-8")
    ).hexdigest()


def make_run_id(request):
    arch = request["architecture"]
    target = request["target"]

    dataflow_short = {
        "weight_stationary": "ws",
        "output_stationary": "os",
        "input_stationary": "is"
    }.get(
        arch["dataflow"],
        slug(arch["dataflow"])
    )

    freq = target["frequency_mhz"]

    if float(freq).is_integer():
        freq_text = str(int(freq))
    else:
        freq_text = str(freq).replace(".", "p")

    prompt_hash = sha256_text(
        request["original_prompt"]
    )[:8]

    timestamp = datetime.now(
        timezone.utc
    ).strftime("%Y%m%dT%H%M%SZ")

    return (
        f"{dataflow_short}"
        f"_n{arch['n']}"
        f"_{request['technology']}"
        f"_{freq_text}mhz"
        f"_{timestamp}"
        f"_{prompt_hash}"
    )


def build_context(prompt):
    request = build_request(prompt)

    run_id = make_run_id(request)

    run_dir = (
        ROOT
        / "results"
        / "runs"
        / run_id
    )

    config_dir = (
        ROOT
        / "configs"
        / "generated"
        / run_id
    )

    rtl_dir = (
        run_dir
        / "rtl"
    )

    verification_dir = (
        run_dir
        / "verification"
    )

    eda_dir = (
        run_dir
        / "eda"
    )

    closure_dir = (
        run_dir
        / "closure"
    )

    artifacts_dir = (
        run_dir
        / "artifacts"
    )

    context = {
        "schema":
            "accelclosure.run_context.v1",

        "run_id":
            run_id,

        "created_utc":
            datetime.now(
                timezone.utc
            ).isoformat(),

        "request":
            request,

        "parameters": {
            "n":
                request["architecture"]["n"],

            "rows":
                request["architecture"]["rows"],

            "cols":
                request["architecture"]["cols"],

            "dataflow":
                request["architecture"]["dataflow"],

            "activation_width":
                8,

            "weight_width":
                8,

            "accumulator_width":
                32,

            "technology":
                request["technology"],

            "target_frequency_mhz":
                request["target"]["frequency_mhz"],

            "target_period_ns":
                request["target"]["period_ns"],

            "optimization_objective":
                request["optimization_objective"]
        },

        "policy": {
            "target_clock_relaxation_allowed":
                False,

            "reuse_metrics_from_reference_run":
                False,

            "functional_reverification_after_rtl_change":
                True,

            "eda_measurement_required":
                True,

            "agent_can_self_declare_closure":
                False
        },

        "paths": {
            "run_dir":
                str(run_dir.relative_to(ROOT)),

            "config_dir":
                str(config_dir.relative_to(ROOT)),

            "rtl_dir":
                str(rtl_dir.relative_to(ROOT)),

            "verification_dir":
                str(
                    verification_dir.relative_to(ROOT)
                ),

            "eda_dir":
                str(eda_dir.relative_to(ROOT)),

            "closure_dir":
                str(closure_dir.relative_to(ROOT)),

            "artifacts_dir":
                str(artifacts_dir.relative_to(ROOT))
        },

        "stages": {
            "request_parsed":
                True,

            "contract_generated":
                False,

            "contract_validated":
                False,

            "rtl_generated":
                False,

            "lint_passed":
                False,

            "functional_verification_passed":
                False,

            "synthesis_passed":
                False,

            "sta_complete":
                False,

            "target_met_post_synthesis":
                False,

            "closure_agent_invoked":
                False,

            "physical_design_complete":
                False,

            "target_met_post_route":
                False,

            "gds_generated":
                False,

            "run_record_verified":
                False
        }
    }

    return context


def initialize_run(context):
    paths = context["paths"]

    for key in (
        "run_dir",
        "config_dir",
        "rtl_dir",
        "verification_dir",
        "eda_dir",
        "closure_dir",
        "artifacts_dir"
    ):
        (
            ROOT
            / paths[key]
        ).mkdir(
            parents=True,
            exist_ok=True
        )

    run_dir = (
        ROOT
        / paths["run_dir"]
    )

    request_path = (
        run_dir
        / "request.json"
    )

    context_path = (
        run_dir
        / "run_context.json"
    )

    request_path.write_text(
        json.dumps(
            context["request"],
            indent=2
        )
        + "\n"
    )

    context_path.write_text(
        json.dumps(
            context,
            indent=2
        )
        + "\n"
    )

    return context_path


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Create a canonical AccelClosure "
            "execution context from a user request."
        )
    )

    parser.add_argument(
        "request",
        help="Natural-language accelerator request"
    )

    args = parser.parse_args()

    try:
        context = build_context(
            args.request
        )

    except RequestError as exc:
        print(
            f"REQUEST_REJECTED: {exc}"
        )
        return 1

    context_path = initialize_run(
        context
    )

    print("ACCELCLOSURE_RUN_CONTEXT_CREATED")
    print(
        f"run_id={context['run_id']}"
    )

    params = context["parameters"]

    print(
        f"N={params['n']}"
    )

    print(
        f"dataflow={params['dataflow']}"
    )

    print(
        "target_frequency_mhz="
        f"{params['target_frequency_mhz']}"
    )

    print(
        "target_period_ns="
        f"{params['target_period_ns']}"
    )

    print(
        f"technology={params['technology']}"
    )

    print(
        "optimization_objective="
        f"{params['optimization_objective']}"
    )

    print(
        f"context={context_path}"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
