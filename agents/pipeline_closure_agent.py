import json
import os
import re
from pathlib import Path

from chia.base.ChiaFunction import get
from chia.models.opencode import (
    OpenCodeLLM,
    AdditionalModelProvider,
    QueryResult,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]

PERSIST_ROOT = Path(
    os.environ.get(
        "ACCELCLOSURE_ROOT",
        str(PROJECT_ROOT),
    )
).expanduser().resolve()

RTL_DIR = PERSIST_ROOT / "rtl"
RESULTS_DIR = PERSIST_ROOT / "results"
CONFIG_DIR = PERSIST_ROOT / "configs"

MODEL = "google-vertex/gemini-3.1-pro-preview"


def load_json(path):
    with Path(path).open() as f:
        return json.load(f)


def extract_json(text):
    text = text.strip()

    text = re.sub(
        r"^```(?:json)?\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )

    text = re.sub(
        r"\s*```$",
        "",
        text,
    )

    first = text.find("{")
    last = text.rfind("}")

    if first == -1 or last == -1:
        raise ValueError(
            "No JSON object found in Closure Agent response"
        )

    return json.loads(
        text[first:last + 1]
    )


def extract_sta_evidence(text):
    def number(pattern):
        m = re.search(
            pattern,
            text,
            flags=re.IGNORECASE,
        )

        if not m:
            return None

        return float(m.group(1))

    def string(pattern):
        m = re.search(
            pattern,
            text,
            flags=re.IGNORECASE,
        )

        if not m:
            return None

        return m.group(1).strip()

    return {
        "worst_slack_ns": number(
            r"worst slack max\s+([-+]?\d+(?:\.\d+)?)"
        ),
        "wns_ns": number(
            r"wns max\s+([-+]?\d+(?:\.\d+)?)"
        ),
        "tns_ns": number(
            r"tns max\s+([-+]?\d+(?:\.\d+)?)"
        ),
        "reported_min_period_ns": number(
            r"period_min\s*=\s*"
            r"([-+]?\d+(?:\.\d+)?)"
        ),
        "reported_core_fmax_mhz": number(
            r"fmax\s*=\s*"
            r"([-+]?\d+(?:\.\d+)?)"
        ),
        "critical_startpoint": string(
            r"Startpoint:\s*([^\n]+)"
        ),
        "critical_endpoint": string(
            r"Endpoint:\s*([^\n]+)"
        ),
    }


def make_prompt(
    baseline,
    sta_evidence,
    pe_rtl,
    array_rtl,
    golden_context,
    pipeline_policy,
):
    return f"""
You are the AccelClosure Pipeline Closure Agent.

You are not performing a cosmetic RTL repair.

A real Sky130 synthesis and static timing analysis run has shown
that the generated accelerator does not meet the user's fixed
150 MHz requirement.

Your task is to redesign the accelerator MICROARCHITECTURE so
that it is professionally pipelined while preserving the requested
architecture and functionality.

The target clock MUST remain 6.667 ns / 150 MHz.

Do NOT relax the clock requirement.

================ VERIFIED BASELINE ================

{json.dumps(baseline, indent=2)}

================ REAL STA EVIDENCE ================

{json.dumps(sta_evidence, indent=2)}

================ CURRENT PE RTL ================

{pe_rtl}

================ CURRENT ARRAY RTL ================

{array_rtl}

================ GOLDEN ARCHITECTURE CONTEXT ================

{json.dumps(golden_context, indent=2)}

================ PIPELINE POLICY ================

{json.dumps(pipeline_policy, indent=2)}

================ ARCHITECTURAL INVARIANTS ================

Preserve:

- 16x16 parameterizable weight-stationary systolic architecture.
- Exactly N*N processing elements.
- Signed INT8 activations.
- Signed INT8 stationary weights.
- Signed INT32 partial-sum accumulation.
- Activation flow left to right.
- Partial-sum flow top to bottom.
- Weight B[k][j] remains stationary at PE(k,j).
- Existing external module port names and widths.
- Synthesizable SystemVerilog.
- Correct reset behavior.

================ TIMING PROBLEM ================

The verified baseline has a timing-critical input-to-register path
from the activation input through substantial PE arithmetic before
the partial-sum output register.

The current PE performs multiplication and accumulation in the
same sequential interval.

You must remove this long MAC combinational path through deliberate
pipeline partitioning.

================ REQUIRED PIPELINE BEHAVIOR ================

Design a professional accelerator pipeline.

At minimum, strongly consider separating:

    Stage A:
        capture/alignment and signed INT8 multiplication

    Stage B:
        INT32 accumulation and registered propagation

A product register between multiplication and accumulation is
appropriate unless you can demonstrate a better synthesizable
partition.

If the partial sum must be delayed to align with the registered
product, pipeline it.

If activation propagation requires additional delay so that
activation and partial-sum wavefronts remain aligned between PEs,
pipeline activation accordingly.

The following invariant is mandatory:

    activation_hop_latency_cycles
        ==
    psum_hop_latency_cycles

Valid signals must travel with their corresponding data.

You MAY add synchronous array-boundary input registers if useful
to prevent a primary input from directly feeding substantial
arithmetic in the same timing interval.

If boundary registers are introduced, activation and partial-sum
boundary timing must remain mutually aligned.

Do not introduce fake timing exceptions.

Do not add:
- clock gating
- power gating
- DMA
- CPU interface
- SRAM macros
- behavioral matrix multiplication
- fabricated timing claims

================ IMPORTANT ================

This redesign is UNVERIFIED until Verilator and Sky130 synthesis
are rerun.

Do not claim that 150 MHz has been achieved.

Return ONLY valid JSON.

No Markdown fences.

Required schema:

{{
  "closure_version": "1.0",

  "failure_class": "TIMING_ARCHITECTURE",

  "root_cause": "...",

  "architecture_change": "...",

  "pipeline_metadata": {{
    "boundary_input_registers": true,
    "pe_pipeline_stages": 2,
    "activation_hop_latency_cycles": 2,
    "psum_hop_latency_cycles": 2,
    "valid_alignment_preserved": true,
    "weight_stationary_preserved": true,
    "external_schedule_change_required": true
  }},

  "timing_reasoning": [
    "..."
  ],

  "files": [
    {{
      "path": "rtl/accelclosure_ws_pe.sv",
      "content": "..."
    }},
    {{
      "path": "rtl/accelclosure_ws_array.sv",
      "content": "..."
    }}
  ],

  "verification_required": [
    "Verilator lint",
    "Directed GEMM verification",
    "Random signed INT8 GEMM regression",
    "Sky130 synthesis at 6.667 ns",
    "OpenROAD STA at 6.667 ns"
  ]
}}
"""


def validate_bundle(bundle):
    errors = []

    if bundle.get("failure_class") != "TIMING_ARCHITECTURE":
        errors.append(
            "failure_class must be TIMING_ARCHITECTURE"
        )

    metadata = bundle.get(
        "pipeline_metadata"
    )

    if not isinstance(metadata, dict):
        errors.append(
            "pipeline_metadata missing"
        )
    else:
        pe_stages = metadata.get(
            "pe_pipeline_stages"
        )

        act_latency = metadata.get(
            "activation_hop_latency_cycles"
        )

        psum_latency = metadata.get(
            "psum_hop_latency_cycles"
        )

        if not isinstance(pe_stages, int):
            errors.append(
                "pe_pipeline_stages must be integer"
            )
        elif pe_stages < 2:
            errors.append(
                "PE must have at least 2 pipeline stages"
            )

        if act_latency != psum_latency:
            errors.append(
                "Activation and psum hop latency must match"
            )

        if not isinstance(act_latency, int):
            errors.append(
                "Hop latency must be integer"
            )
        elif act_latency < 2:
            errors.append(
                "Hop latency must be >= 2 cycles"
            )

        if metadata.get(
            "valid_alignment_preserved"
        ) is not True:
            errors.append(
                "Valid alignment must be preserved"
            )

        if metadata.get(
            "weight_stationary_preserved"
        ) is not True:
            errors.append(
                "Weight stationarity must be preserved"
            )

    files = bundle.get(
        "files",
        [],
    )

    expected = {
        "rtl/accelclosure_ws_pe.sv",
        "rtl/accelclosure_ws_array.sv",
    }

    actual = {
        item.get("path")
        for item in files
        if isinstance(item, dict)
    }

    if actual != expected:
        errors.append(
            f"Expected exactly {sorted(expected)}, "
            f"got {sorted(actual)}"
        )

    for item in files:
        content = item.get(
            "content",
            "",
        )

        if not content.strip():
            errors.append(
                f"Empty content: {item.get('path')}"
            )

        if "```" in content:
            errors.append(
                f"Markdown fence in {item.get('path')}"
            )

    return errors


def main():
    project = os.environ.get(
        "GOOGLE_CLOUD_PROJECT"
    )

    if not project:
        raise RuntimeError(
            "GOOGLE_CLOUD_PROJECT is not set"
        )

    pe_path = (
        RTL_DIR
        / "accelclosure_ws_pe.sv"
    )

    array_path = (
        RTL_DIR
        / "accelclosure_ws_array.sv"
    )

    baseline_path = (
        RESULTS_DIR
        / "closure"
        / "baseline_iter0"
        / "summary.json"
    )

    sta_path = (
        RESULTS_DIR
        / "closure"
        / "iter0_150mhz"
        / "sta"
        / "prelayout_sta.log"
    )

    golden_path = (
        RESULTS_DIR
        / "design_contract_golden_context.json"
    )

    policy_path = (
        CONFIG_DIR
        / "policies"
        / "accelerator_pipeline_policy.json"
    )

    baseline = load_json(
        baseline_path
    )

    golden_context = load_json(
        golden_path
    )

    pipeline_policy = load_json(
        policy_path
    )

    pe_rtl = pe_path.read_text()
    array_rtl = array_path.read_text()

    sta_text = sta_path.read_text()

    sta_evidence = extract_sta_evidence(
        sta_text
    )

    print(
        "[AccelClosure] REAL_STA_EVIDENCE:"
    )
    print(
        json.dumps(
            sta_evidence,
            indent=2,
        )
    )

    vertex = AdditionalModelProvider(
        id="google-vertex",
        npm="@ai-sdk/google-vertex",
        name="Google Vertex AI",
        models=[
            "gemini-3.1-pro-preview"
        ],
        options={
            "project": project,
            "location": "global",
        },
    )

    llm = OpenCodeLLM(
        model=MODEL,
        additional_providers=[
            vertex
        ],
    )

    prompt = make_prompt(
        baseline,
        sta_evidence,
        pe_rtl,
        array_rtl,
        golden_context,
        pipeline_policy,
    )

    print(
        "[AccelClosure] Dispatching "
        "pipeline closure to Gemini..."
    )

    response: QueryResult = get(
        llm.prompt.chia_remote(
            llm,
            prompt,
        )
    )

    raw = response.result

    closure_dir = (
        RESULTS_DIR
        / "closure"
    )

    closure_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    (
        closure_dir
        / "pipeline_iter1_agent_raw.txt"
    ).write_text(
        raw
    )

    bundle = extract_json(
        raw
    )

    errors = validate_bundle(
        bundle
    )

    if errors:
        raise RuntimeError(
            "Pipeline closure bundle invalid: "
            + "; ".join(errors)
        )

    backup_dir = (
        RTL_DIR
        / "revisions"
        / "v4_before_pipeline_closure_agent"
    )

    backup_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    (
        backup_dir
        / pe_path.name
    ).write_text(
        pe_rtl
    )

    (
        backup_dir
        / array_path.name
    ).write_text(
        array_rtl
    )

    for item in bundle["files"]:
        destination = (
            PERSIST_ROOT
            / item["path"]
        )

        destination.write_text(
            item["content"]
        )

        print(
            "[AccelClosure] PIPELINED:",
            destination,
        )

    report = {
        "status":
            "PIPELINE_REDESIGN_UNVERIFIED",

        "closure_version":
            bundle.get(
                "closure_version"
            ),

        "failure_class":
            bundle.get(
                "failure_class"
            ),

        "root_cause":
            bundle.get(
                "root_cause"
            ),

        "architecture_change":
            bundle.get(
                "architecture_change"
            ),

        "pipeline_metadata":
            bundle.get(
                "pipeline_metadata"
            ),

        "timing_reasoning":
            bundle.get(
                "timing_reasoning",
                [],
            ),

        "verification_required":
            bundle.get(
                "verification_required",
                [],
            ),

        "source_tool":
            "OpenROAD/OpenSTA",

        "source_sta":
            str(sta_path),

        "target_period_ns":
            6.667,

        "target_frequency_mhz":
            150.0,

        "target_relaxed":
            False,

        "pre_redesign_backup":
            "rtl/revisions/"
            "v4_before_pipeline_closure_agent",

        "verified":
            False,
    }

    report_path = (
        closure_dir
        / "pipeline_iter1_agent_report.json"
    )

    report_path.write_text(
        json.dumps(
            report,
            indent=2,
        )
    )

    print("")
    print(
        json.dumps(
            report,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
