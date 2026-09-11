import argparse
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
    os.environ.get("ACCELCLOSURE_ROOT", str(PROJECT_ROOT))
).expanduser().resolve()

RESULTS_DIR = PERSIST_ROOT / "results"
RTL_DIR = PERSIST_ROOT / "rtl"

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
    text = re.sub(r"\s*```$", "", text)

    first = text.find("{")
    last = text.rfind("}")

    if first == -1 or last == -1 or last <= first:
        raise ValueError("No JSON object found in Gemini response")

    return json.loads(text[first:last + 1])


def make_prompt(
    contract,
    golden_context,
    pipeline_policy,
):
    req = contract["requested_constraints"]

    rows = req.get("array_rows")
    cols = req.get("array_columns")

    if not isinstance(rows, int) or not isinstance(cols, int):
        raise ValueError(
            "Contract array dimensions must be integers"
        )

    if rows != cols:
        raise ValueError(
            "Current AccelClosure WS generator requires a square array"
        )

    n = rows

    def precision_bits(value, field_name):
        """
        Parse the FIRST canonical INT<n> precision token only.

        Examples:
            INT8                         -> 8
            INT32                       -> 32
            INT32 conservative ... INT8 -> 32

        Never concatenate unrelated digits from descriptive prose.
        """
        match = re.search(
            r"\bINT\s*(\d+)\b",
            str(value),
            flags=re.IGNORECASE,
        )

        if not match:
            raise ValueError(
                f"Could not determine canonical INT<n> precision "
                f"for {field_name}: {value}"
            )

        return int(match.group(1))

    data_w = precision_bits(
        req.get("input_precision"),
        "input_precision",
    )

    weight_w = precision_bits(
        req.get("weight_precision"),
        "weight_precision",
    )

    if data_w != weight_w:
        raise ValueError(
            "Current WS PE requires equal activation and weight widths"
        )

    acc_w = precision_bits(
        contract["proposed_architecture"].get(
            "accumulator_precision",
            "INT32",
        ),
        "accumulator_precision",
    )

    target_frequency_mhz = req.get(
        "target_frequency_mhz"
    )

    return f"""
You are the AccelClosure RTL Generation Agent.

Generate synthesizable SystemVerilog for the VALIDATED accelerator contract.

You are grounded by a pinned Berkeley Gemmini reference. Use the supplied
reference as architectural guidance, but DO NOT copy Gemmini source code.
Generate a clean independent SystemVerilog implementation.

================ VALIDATED DESIGN CONTRACT ================

{json.dumps(contract, indent=2)}

================ GOLDEN REFERENCE CONTEXT ================

{json.dumps(golden_context, indent=2)}

================ ACCELCLOSURE PIPELINE POLICY ================

{json.dumps(pipeline_policy, indent=2)}

The pipeline policy above is mandatory.

Interpret "fully pipelined systolic array" as follows:

- Input boundary registers are MANDATORY.
- Every PE-to-PE activation hop must cross a sequential register boundary.
- Every PE-to-PE partial-sum hop must cross a sequential register boundary.
- Every associated valid signal must cross matching sequential boundaries.
- Do NOT create combinational arithmetic chains spanning multiple PEs.
- Activation data and activation-valid must remain cycle-aligned.
- Partial-sum data and partial-sum-valid must remain cycle-aligned.
- Activation and partial-sum wavefront latencies must remain structurally compatible.
- The steady-state initiation interval MUST be one cycle after pipeline fill.
- The PE arithmetic pipeline MUST contain at least TWO sequential stages.
- Stage 1 performs signed multiplication.
- Stage 2 performs accumulation.
- A sequential register between multiplication and accumulation is MANDATORY.
- A single-stage multiply-and-accumulate implementation is FORBIDDEN.
- Additional arithmetic stages may be added later only if real STA requires them.
- Never relax the requested clock in generated RTL.
- Do not claim timing closure from architecture alone.

================ REQUIRED IMPLEMENTATION ================

Generate exactly TWO synthesizable SystemVerilog files:

1. rtl/accelclosure_ws_pe.sv
2. rtl/accelclosure_ws_array.sv

Do not generate a testbench.

------------------------------------------------------------
PE REQUIREMENTS
------------------------------------------------------------

Module name:

accelclosure_ws_pe

Parameters:

DATA_W = {data_w}
ACC_W  = {acc_w}

Required ports:

input  logic clk
input  logic rst_n

input  logic weight_load
input  logic signed [DATA_W-1:0] weight_in

input  logic act_valid_in
input  logic signed [DATA_W-1:0] act_in

input  logic psum_valid_in
input  logic signed [ACC_W-1:0] psum_in

output logic act_valid_out
output logic signed [DATA_W-1:0] act_out

output logic psum_valid_out
output logic signed [ACC_W-1:0] psum_out

Behavior:

- The PE stores one stationary weight in a register.
- weight_load updates the stationary weight.
- The PE MUST implement a minimum two-stage arithmetic pipeline.
- Use the exact registered multiplication signal name `mult_reg`.
- Use registered Stage-1 alignment signals including `act_stg1` and `psum_stg1`.

Stage 1:
- Capture the incoming activation, partial sum, and corresponding valid state.
- Perform SIGNED DATA_W x DATA_W multiplication.
- Store the multiplication result in `mult_reg`.
- `mult_reg` therefore forms the mandatory sequential boundary between multiplication and accumulation.

Stage 2:
- Sign-extend the REGISTERED `mult_reg` value to ACC_W.
- Add that registered product to the correspondingly registered partial sum.
- Register the resulting partial sum into psum_out.
- Register/propagate activation and valid signals with matching total hop latency.

Required behavior when the aligned Stage-1 activation and partial-sum valids are asserted:

      psum_out <= psum_stg1 + sign_extend(mult_reg)

- Do NOT implement `psum_out <= psum_in + act_in * stationary_weight`.
- Do NOT implement multiplication and accumulation in the same sequential interval.
- Multiplication must be signed.
- Product must be EXPLICITLY sign-extended before adding to ACC_W.
- Do NOT rely on implicit SystemVerilog width extension.
- Do NOT write `assign mult_reg_ext = mult_reg;` when ACC_W is wider than 2*DATA_W.
- The registered multiplication result is signed [2*DATA_W-1:0].
- The ACC_W-wide extension must explicitly replicate the registered product sign bit.
- Use an explicit structure equivalent to:

      assign mult_reg_ext = {{
          {{(ACC_W-(2*DATA_W)){{mult_reg[2*DATA_W-1]}}}},
          mult_reg
      }};

- This product extension must generate no Verilator WIDTH warning.
- ACC_W must be at least 2*DATA_W for the current supported product family.
- Activation hop latency must be two cycles.
- Partial-sum hop latency must be two cycles.
- act_valid_out must correspond to act_out.
- psum_valid_out must correspond to psum_out.
- Reset all pipeline state and valid outputs deterministically.
- Preserve steady-state initiation interval II=1.
- Do not use unsynthesizable constructs.

------------------------------------------------------------
ARRAY REQUIREMENTS
------------------------------------------------------------

Module name:

accelclosure_ws_array

Parameters:

N      = {n}
DATA_W = {data_w}
ACC_W  = {acc_w}

Required ports:

input logic clk
input logic rst_n

input logic weight_load_valid
input logic [$clog2(N)-1:0] weight_load_row
input logic signed [N*DATA_W-1:0] weight_load_data

input logic [N-1:0] act_valid_in
input logic signed [N*DATA_W-1:0] act_data_in

input logic [N-1:0] psum_valid_in
input logic signed [N*ACC_W-1:0] psum_data_in

output logic [N-1:0] result_valid_out
output logic signed [N*ACC_W-1:0] result_data_out

Structural requirements:

- Instantiate exactly N*N accelclosure_ws_pe instances.
- Each PE represents coordinate (row=k, column=j).
- Stationary weight at (k,j) represents B[k][j].
- weight_load_row selects one PE row.
- weight_load_data contains N weights for that row.
- Activation flows LEFT -> RIGHT through each PE row.
- Partial sum flows TOP -> BOTTOM through each PE column.
- Bottom-row partial sums form result_data_out.
- Bottom-row partial-sum valids form result_valid_out.

- ALL external accelerator inputs MUST first cross synchronous array-level
  boundary registers before being connected to any PE.
- Use these exact boundary-register signal names:
    weight_load_valid_reg
    weight_load_row_reg
    weight_load_data_reg
    act_valid_in_reg
    act_data_in_reg
    psum_valid_in_reg
    psum_data_in_reg
- Mesh activation boundary connections MUST originate from act_valid_in_reg
  and act_data_in_reg.
- Mesh partial-sum boundary connections MUST originate from psum_valid_in_reg
  and psum_data_in_reg.
- PE weight-loading logic MUST consume the registered weight-load signals.
- Boundary-register latency is exactly one cycle.

- Use generate loops.
- Do not implement the matrix multiplication with behavioral nested loops.
- Do not replace the systolic fabric with a combinational dot-product tree.

Systolic scheduling model:

For output row i beginning at logical cycle T:

- The mandatory PE hop latency is 2 cycles.
- A[i][k] enters PE row k from the left at cycle T + 2*k.
- zero partial sum for output column j enters the top at cycle T + 2*j.
- The one-cycle array input-boundary latency is common to both streams.
- These wavefronts therefore remain aligned at PE(k,j).
- Multiple output rows may be launched one cycle apart after pipeline fill.
- The steady-state initiation interval remains II=1.

The RTL fabric itself does NOT need to generate this skew.
The external verification driver will generate the pipeline-aware input schedule.

------------------------------------------------------------
ENGINEERING RULES
------------------------------------------------------------

- SystemVerilog only.
- Synthesizable RTL only.
- Avoid vendor-specific primitives.
- No clock gating in this first version.
- No power gating.
- No SRAM macros.
- No DMA.
- No CPU interface.
- No fabricated timing/PPA claims.
- Keep the implementation simple enough for Verilator and Yosys.
- Preserve signed arithmetic.
- Prefer explicit, readable structural connections.
- The implementation must parameterize with N.
- For THIS run, elaborate the array at N={n}.
- Do not substitute another array dimension.
- The requested target frequency is {target_frequency_mhz} MHz.
- This frequency is a REQUIREMENT, not a measured result.
- Do not claim timing closure before EDA measurement.

Return ONLY valid JSON.

No Markdown.
No ``` fences.

Required output schema:

{{
  "generator_version": "1.1",
  "golden_reference_id": "gemmini_systolic_array_v1",
  "design_summary": "...",
  "pipeline_metadata": {{
    "boundary_input_registers": true,
    "boundary_latency_cycles": 1,
    "pe_pipeline_stages": 2,
    "activation_hop_latency_cycles": 2,
    "psum_hop_latency_cycles": 2,
    "valid_alignment_preserved": true,
    "weight_stationary_preserved": true,
    "initiation_interval_cycles": 1,
    "multiply_accumulate_separated": true,
    "external_schedule_change_required": true
  }},
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
  "design_notes": [],
  "unverified_assumptions": []
}}
"""


def validate_bundle(bundle):
    errors = []

    if bundle.get("golden_reference_id") != "gemmini_systolic_array_v1":
        errors.append("Incorrect golden reference ID")

    metadata = bundle.get("pipeline_metadata")

    if not isinstance(metadata, dict):
        errors.append("pipeline_metadata must be an object")
    else:
        required_true = (
            "boundary_input_registers",
            "valid_alignment_preserved",
            "weight_stationary_preserved",
            "multiply_accumulate_separated",
        )

        for key in required_true:
            if metadata.get(key) is not True:
                errors.append(
                    f"pipeline_metadata.{key} must be true"
                )

        if metadata.get("boundary_latency_cycles") != 1:
            errors.append(
                "pipeline_metadata.boundary_latency_cycles must be 1"
            )

        stages = metadata.get("pe_pipeline_stages")

        if not isinstance(stages, int) or stages < 2:
            errors.append(
                "pipeline_metadata.pe_pipeline_stages must be >= 2"
            )

        act_hop = metadata.get(
            "activation_hop_latency_cycles"
        )

        psum_hop = metadata.get(
            "psum_hop_latency_cycles"
        )

        if (
            not isinstance(act_hop, int)
            or not isinstance(psum_hop, int)
            or act_hop < 2
            or psum_hop < 2
            or act_hop != psum_hop
        ):
            errors.append(
                "activation/psum hop latency must be equal and >= 2"
            )

        if metadata.get("initiation_interval_cycles") != 1:
            errors.append(
                "pipeline_metadata.initiation_interval_cycles must be 1"
            )

    files = bundle.get("files")

    if not isinstance(files, list):
        errors.append("files must be a list")
        return errors

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
            f"Expected exactly {sorted(expected)}, got {sorted(actual)}"
        )

    for item in files:
        if not isinstance(item, dict):
            errors.append("Invalid file object")
            continue

        path = item.get("path")
        content = item.get("content")

        if not isinstance(content, str) or not content.strip():
            errors.append(f"Empty RTL content for {path}")
            continue

        if "```" in content:
            errors.append(f"Markdown fence found in {path}")

        if path and path.endswith(".sv"):
            module_name = Path(path).stem

            if f"module {module_name}" not in content:
                errors.append(
                    f"Expected module {module_name} not found in {path}"
                )

            if path == "rtl/accelclosure_ws_pe.sv":
                compact = "".join(
                    content.split()
                )

                forbidden_extensions = (
                    "assignmult_reg_ext=mult_reg;",
                    "assignprod_extended=mult_reg;",
                    "assignproduct_extended=mult_reg;",
                )

                for forbidden in forbidden_extensions:
                    if forbidden in compact:
                        errors.append(
                            "PE uses implicit product width extension; "
                            "explicit signed replication to ACC_W is required"
                        )

    return errors


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--contract",
        default="results/design_contract_v1.json",
    )

    parser.add_argument(
        "--context",
        default="results/design_contract_golden_context.json",
    )

    parser.add_argument(
        "--validation",
        default="results/contract_validation_report.json",
    )

    parser.add_argument(
        "--pipeline-policy",
        default="configs/product/pipeline_policy.json",
    )

    parser.add_argument(
        "--results-dir",
        default="results",
    )

    parser.add_argument(
        "--rtl-dir",
        default="rtl",
    )

    args = parser.parse_args()

    results_dir = Path(
        args.results_dir
    )

    if not results_dir.is_absolute():
        results_dir = (
            PERSIST_ROOT
            / results_dir
        )

    rtl_dir = Path(
        args.rtl_dir
    )

    if not rtl_dir.is_absolute():
        rtl_dir = (
            PERSIST_ROOT
            / rtl_dir
        )

    contract = load_json(PERSIST_ROOT / args.contract)
    context = load_json(PERSIST_ROOT / args.context)
    validation = load_json(PERSIST_ROOT / args.validation)

    pipeline_policy = load_json(
        PERSIST_ROOT
        / args.pipeline_policy
    )

    if validation.get("status") != "VALID":
        raise RuntimeError(
            "Design contract is not VALID. RTL generation blocked."
        )

    if validation.get("ready_for_rtl_generation") is not True:
        raise RuntimeError(
            "Validator has not authorized RTL generation."
        )

    project = os.environ.get("GOOGLE_CLOUD_PROJECT")

    if not project:
        raise RuntimeError("GOOGLE_CLOUD_PROJECT is not set")

    vertex = AdditionalModelProvider(
        id="google-vertex",
        npm="@ai-sdk/google-vertex",
        name="Google Vertex AI",
        models=["gemini-3.1-pro-preview"],
        options={
            "project": project,
            "location": "global",
        },
    )

    llm = OpenCodeLLM(
        model=MODEL,
        additional_providers=[vertex],
    )

    prompt = make_prompt(
        contract,
        context,
        pipeline_policy,
    )

    print("[AccelClosure] Contract gate: VALID")
    print("[AccelClosure] Golden grounding: gemmini_systolic_array_v1")
    print("[AccelClosure] Dispatching RTL generation to Gemini...")

    response: QueryResult = get(
        llm.prompt.chia_remote(
            llm,
            prompt,
        )
    )

    raw = response.result

    results_dir.mkdir(parents=True, exist_ok=True)
    rtl_dir.mkdir(parents=True, exist_ok=True)

    raw_path = results_dir / "rtl_generation_raw.txt"
    raw_path.write_text(raw)

    bundle = extract_json(raw)

    errors = validate_bundle(bundle)

    if errors:
        bundle_report = {
            "status": "INVALID_RTL_BUNDLE",
            "errors": errors,
        }

        (
            results_dir / "rtl_generation_report.json"
        ).write_text(
            json.dumps(bundle_report, indent=2)
        )

        raise RuntimeError(
            "Generated RTL bundle failed structural checks: "
            + "; ".join(errors)
        )

    for item in bundle["files"]:
        relative = Path(item["path"])

        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError(
                f"Unsafe generated path: {relative}"
            )

        # Gemini returns canonical paths such as:
        # rtl/accelclosure_ws_pe.sv
        # Store only the basename-relative portion under
        # this run's isolated RTL directory.
        if (
            relative.parts
            and relative.parts[0] == "rtl"
        ):
            relative = Path(
                *relative.parts[1:]
            )

        destination = rtl_dir / relative

        destination.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        destination.write_text(item["content"])

        print(
            "[AccelClosure] WROTE:",
            destination,
        )

    manifest = {
        "status": "RTL_GENERATED_UNVERIFIED",
        "generator_version": bundle.get(
            "generator_version"
        ),
        "golden_reference_id": bundle.get(
            "golden_reference_id"
        ),
        "design_summary": bundle.get(
            "design_summary"
        ),
        "pipeline_metadata": bundle.get(
            "pipeline_metadata"
        ),
        "files": [
            item["path"]
            for item in bundle["files"]
        ],
        "design_notes": bundle.get(
            "design_notes", []
        ),
        "unverified_assumptions": bundle.get(
            "unverified_assumptions", []
        ),
        "functional_verified": False,
        "lint_verified": False,
        "synthesis_verified": False,
    }

    (
        results_dir / "rtl_generation_report.json"
    ).write_text(
        json.dumps(manifest, indent=2)
    )

    print("[AccelClosure] RTL_GENERATED_UNVERIFIED")
    print(
        json.dumps(
            manifest,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
