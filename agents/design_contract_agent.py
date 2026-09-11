import argparse
import json
import os
import re
import sys
from pathlib import Path


# Allow this agent to be executed directly:
#   python agents/design_contract_agent.py
PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from chia.base.ChiaFunction import get
from chia.models.opencode import (
    OpenCodeLLM,
    AdditionalModelProvider,
    QueryResult,
)

from src.reference_context_builder import build_context


# Ray executes jobs from a temporary packaged directory.
# Persist artifacts in the real AccelClosure workspace when provided.
PERSIST_ROOT = Path(
    os.environ.get("ACCELCLOSURE_ROOT", str(PROJECT_ROOT))
).expanduser().resolve()

RESULTS_DIR = PERSIST_ROOT / "results"

MODEL = "google-vertex/gemini-3.1-pro-preview"


def extract_json(text: str):
    text = text.strip()

    # Remove Markdown fences if the model ignored the instruction.
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)

    first = text.find("{")
    last = text.rfind("}")

    if first == -1 or last == -1 or last <= first:
        raise ValueError("No JSON object found in Gemini response")

    return json.loads(text[first:last + 1])


def make_prompt(user_request: str, golden_context: dict) -> str:
    context_json = json.dumps(golden_context, indent=2)

    return f"""
You are the AccelClosure Architect Agent.

Your task is to convert a natural-language AI-accelerator request into a
strict hardware design contract.

You are given GOLDEN REFERENCE material extracted from a pinned,
known upstream hardware architecture. Use this material as engineering
guidance.

IMPORTANT RULES:

1. Do not blindly copy Gemmini.
2. Distinguish USER REQUIREMENTS from your engineering choices.
3. Preserve applicable architectural invariants from the golden reference.
4. If something is not specified, mark it as an assumption or design choice.
5. Do not claim achieved timing, area, power, frequency, or functionality.
   Those must later be measured by real EDA/simulation tools.
6. Frequency in this stage is a TARGET only.
7. If INT32 accumulation is selected, describe it as a conservative
   reference-derived design choice unless mathematically required.
8. Do not assume clock gating, power gating, or other physical optimizations
   are already implemented. Such techniques may only be proposed as future
   design variables until verified.
7. The generated implementation will later be independently verified.
8. Return ONLY valid JSON.
9. Do not return Markdown.
10. Do not wrap the JSON in ``` fences.

USER REQUEST:
{user_request}

GOLDEN REFERENCE CONTEXT:
{context_json}

Return exactly one JSON object using this top-level structure:

{{
  "contract_version": "1.0",

  "user_request": "...",

  "requested_constraints": {{
    "workload": [],
    "technology": null,
    "target_frequency_mhz": null,
    "array_rows": null,
    "array_columns": null,
    "dataflow": null,
    "input_precision": null,
    "weight_precision": null
  }},

  "proposed_architecture": {{
    "architecture_class": null,
    "pe_operation": null,
    "accumulator_precision": null,
    "rtl_language": "SystemVerilog",
    "pipeline_strategy": null,
    "memory_strategy": null
  }},

  "golden_grounding": {{
    "reference_id": null,
    "source_commit": null,
    "principles_used": [],
    "source_files_used": []
  }},

  "architectural_invariants": [],

  "assumptions": [],

  "design_variables": [],

  "validation_plan": {{
    "functional": [],
    "synthesis": [],
    "physical_design": []
  }},

  "measurement_status": {{
    "functional_verified": false,
    "timing_measured": false,
    "area_measured": false,
    "power_measured": false,
    "physical_design_completed": false
  }}
}}
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--request",
        required=True,
        help="Natural-language accelerator design request",
    )
    parser.add_argument(
        "--output",
        default="results/design_contract_v1.json",
    )

    parser.add_argument(
        "--context-output",
        default="results/design_contract_golden_context.json",
    )

    parser.add_argument(
        "--raw-output",
        default="results/design_contract_raw.txt",
    )

    args = parser.parse_args()

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    print("[AccelClosure] Building golden-reference context...")

    golden_context = build_context(args.request)

    if golden_context.get("status") != "REFERENCE_FOUND":
        raise RuntimeError(
            "No appropriate golden reference found for this request"
        )

    context_path = PERSIST_ROOT / args.context_output

    context_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    context_path.write_text(
        json.dumps(golden_context, indent=2)
        + "\n"
    )

    print(
        "[AccelClosure] Golden reference:",
        golden_context["reference"]["id"],
    )

    print(
        "[AccelClosure] Source files:",
        len(golden_context["source_context"]),
    )

    project = os.environ.get("GOOGLE_CLOUD_PROJECT")

    if not project:
        raise RuntimeError(
            "GOOGLE_CLOUD_PROJECT is not set inside the Ray job"
        )

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
        args.request,
        golden_context,
    )

    print("[AccelClosure] Dispatching grounded request to Gemini...")

    response: QueryResult = get(
        llm.prompt.chia_remote(
            llm,
            prompt,
        )
    )

    raw = response.result

    raw_path = PERSIST_ROOT / args.raw_output

    raw_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    raw_path.write_text(raw)

    contract = extract_json(raw)

    output_path = PERSIST_ROOT / args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(contract, indent=2)
    )

    print("[AccelClosure] DESIGN_CONTRACT_CREATED")
    print("[AccelClosure] Output:", output_path)

    print("\n================ DESIGN CONTRACT ================\n")
    print(json.dumps(contract, indent=2))


if __name__ == "__main__":
    main()
