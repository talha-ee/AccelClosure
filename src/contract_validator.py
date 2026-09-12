import argparse
import json
import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_CONTRACT = PROJECT_ROOT / "results" / "design_contract_v1.json"
DEFAULT_CONTEXT = PROJECT_ROOT / "results" / "design_contract_golden_context.json"
DEFAULT_CARD = (
    PROJECT_ROOT
    / "golden"
    / "knowledge"
    / "cards"
    / "gemmini_systolic_array.json"
)


ALLOWED_DATAFLOWS = {
    "ws",
    "weight-stationary",
    "weight_stationary",
    "os",
    "output-stationary",
    "output_stationary",
    "both",
}

PRECISION_RE = re.compile(r"^INT(\d+)$", re.IGNORECASE)


def load_json(path: Path):
    with path.open() as f:
        return json.load(f)


def precision_bits(value):
    if not isinstance(value, str):
        return None

    m = PRECISION_RE.match(value.strip())

    if not m:
        return None

    return int(m.group(1))


def is_power_of_two(n):
    return isinstance(n, int) and n > 0 and (n & (n - 1)) == 0


def validate(contract, context, card):
    errors = []
    warnings = []
    checks = []

    def ok(name):
        checks.append(name)

    # -------------------------------------------------
    # 1. Basic schema
    # -------------------------------------------------

    required_top = [
        "contract_version",
        "user_request",
        "requested_constraints",
        "proposed_architecture",
        "golden_grounding",
        "architectural_invariants",
        "assumptions",
        "design_variables",
        "validation_plan",
        "measurement_status",
    ]

    for key in required_top:
        if key not in contract:
            errors.append(f"Missing top-level key: {key}")

    if errors:
        return errors, warnings, checks

    ok("BASIC_SCHEMA")

    req = contract["requested_constraints"]
    grounding = contract["golden_grounding"]
    status = contract["measurement_status"]

    # -------------------------------------------------
    # 2. Golden provenance
    # -------------------------------------------------

    if grounding.get("reference_id") != card.get("id"):
        errors.append(
            "golden_grounding.reference_id does not match golden card"
        )
    else:
        ok("GOLDEN_REFERENCE_ID")

    expected_commit = card.get("source", {}).get("commit")

    if grounding.get("source_commit") != expected_commit:
        errors.append(
            "golden_grounding.source_commit does not match pinned source"
        )
    else:
        ok("GOLDEN_COMMIT")

    context_ref = context.get("reference", {}).get("id")

    if grounding.get("reference_id") != context_ref:
        errors.append(
            "Contract golden reference does not match retrieved context"
        )
    else:
        ok("CONTEXT_PROVENANCE")

    selected_files = set(context.get("selected_source_files", []))
    claimed_files = set(grounding.get("source_files_used", []))

    unknown_files = claimed_files - selected_files

    if unknown_files:
        errors.append(
            "Gemini claimed source files not supplied in context: "
            + ", ".join(sorted(unknown_files))
        )
    else:
        ok("SOURCE_FILES_GROUNDED")

    # -------------------------------------------------
    # 3. Requested architecture constraints
    # -------------------------------------------------

    rows = req.get("array_rows")
    cols = req.get("array_columns")

    if not isinstance(rows, int) or rows < 2:
        errors.append("array_rows must be an integer >= 2")

    if not isinstance(cols, int) or cols < 2:
        errors.append("array_columns must be an integer >= 2")

    if isinstance(rows, int) and isinstance(cols, int):
        if rows != cols:
            errors.append(
                "Current Gemmini-derived golden contract requires square array"
            )
        else:
            ok("SQUARE_ARRAY")

        # Arbitrary positive square dimensions are supported by the
        # parametric WS backend. Fresh configurations still require
        # independent functional and EDA evidence.
        ok("PARAMETRIC_ARRAY_DIMENSION")

    dataflow = str(req.get("dataflow", "")).strip().lower()

    if dataflow not in ALLOWED_DATAFLOWS:
        errors.append(f"Unsupported dataflow: {req.get('dataflow')}")
    else:
        ok("DATAFLOW_VALID")

    input_bits = precision_bits(req.get("input_precision"))
    weight_bits = precision_bits(req.get("weight_precision"))

    if input_bits is None:
        errors.append("input_precision must use INT<n> form")

    if weight_bits is None:
        errors.append("weight_precision must use INT<n> form")

    if input_bits is not None and weight_bits is not None:
        if input_bits != weight_bits:
            errors.append(
                "Gemmini golden invariant requires equal "
                "input and weight widths"
            )
        else:
            ok("INPUT_WEIGHT_WIDTH_MATCH")

    freq = req.get("target_frequency_mhz")

    if not isinstance(freq, (int, float)) or freq <= 0:
        errors.append("target_frequency_mhz must be positive")
    else:
        ok("FREQUENCY_IS_TARGET")

    # -------------------------------------------------
    # 4. No fabricated measured results
    # -------------------------------------------------

    expected_false_flags = [
        "functional_verified",
        "timing_measured",
        "area_measured",
        "power_measured",
        "physical_design_completed",
    ]

    for flag in expected_false_flags:
        if status.get(flag) is not False:
            errors.append(
                f"{flag} must remain false before tool-based validation"
            )

    if not any(
        f"{flag} must remain false" in e
        for flag in expected_false_flags
        for e in errors
    ):
        ok("NO_UNMEASURED_RESULT_CLAIMS")

    # -------------------------------------------------
    # 5. Detect suspicious pre-EDA claims
    # -------------------------------------------------

    pre_eda_sections = {
        "proposed_architecture": contract.get(
            "proposed_architecture", {}
        ),
        "assumptions": contract.get("assumptions", []),
        "design_variables": contract.get("design_variables", []),
    }

    serialized = json.dumps(pre_eda_sections).lower()

    # Detect explicit positive PPA/timing claims.
    # Do NOT flag safe negated phrases such as:
    # "not achieved" or "not measured".
    suspicious_patterns = [
        r"\btiming\s+closed\b",
        r"\btiming\s+closure\s+achieved\b",
        r"\b\d+(?:\.\d+)?\s*mhz\s+(?:is\s+)?achieved\b",
        r"\b(?:meets|met|achieves|achieved)\s+(?:the\s+)?\d+(?:\.\d+)?\s*mhz\b",
        r"\bwns\s*(?:=|is)\s*[-+]?\d+(?:\.\d+)?\b",
        r"\btns\s*(?:=|is)\s*[-+]?\d+(?:\.\d+)?\b",
        r"\barea\s*(?:=|is|of)\s*\d+(?:\.\d+)?\s*(?:mm2|mm\^2|um2|µm2)\b",
        r"\bpower\s*(?:=|is|of)\s*\d+(?:\.\d+)?\s*(?:mw|uw|µw|w)\b",
    ]

    suspicious = [
        pattern
        for pattern in suspicious_patterns
        if re.search(pattern, serialized)
    ]

    if suspicious:
        errors.append(
            "Possible fabricated pre-EDA result claim detected: "
            + ", ".join(suspicious)
        )
    else:
        ok("NO_PRE_EDA_PPA_CLAIMS")

    # Softer language warnings.
    future_overclaims = [
        "ensure sky130 150 mhz",
        "guarantee 150 mhz",
        "guarantee 150 mhz operation",
    ]

    whole_contract = json.dumps(contract).lower()

    for phrase in future_overclaims:
        if phrase in whole_contract:
            warnings.append(
                f"Future-plan wording is too strong: '{phrase}'. "
                "Prefer 'target' or 'evaluate'."
            )

    # -------------------------------------------------
    # 6. Golden card itself must still be unverified
    #    unless separately proven
    # -------------------------------------------------

    ref_status = card.get("reference_status", {})

    if ref_status.get("source_inspected") is not True:
        errors.append("Golden reference source has not been inspected")

    if ref_status.get("locally_execution_verified") is not True:
        warnings.append(
            "Gemmini golden source is inspected but has not yet been "
            "locally execution-verified. It is architectural guidance."
        )

    return errors, warnings, checks


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--contract",
        default=str(DEFAULT_CONTRACT),
    )

    parser.add_argument(
        "--context",
        default=str(DEFAULT_CONTEXT),
    )

    parser.add_argument(
        "--card",
        default=str(DEFAULT_CARD),
    )

    parser.add_argument(
        "--output",
        default=str(
            PROJECT_ROOT
            / "results"
            / "contract_validation_report.json"
        ),
    )

    args = parser.parse_args()

    contract = load_json(Path(args.contract))
    context = load_json(Path(args.context))
    card = load_json(Path(args.card))

    errors, warnings, checks = validate(
        contract,
        context,
        card,
    )

    report = {
        "validator_version": "1.0",
        "status": "VALID" if not errors else "INVALID",
        "checks_passed": checks,
        "warnings": warnings,
        "errors": errors,
        "ready_for_rtl_generation": not errors,
    }

    report_path = Path(
        args.output
    )

    if not report_path.is_absolute():
        report_path = (
            PROJECT_ROOT
            / report_path
        )

    report_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    report_path.write_text(
        json.dumps(report, indent=2)
        + "\n"
    )

    print(json.dumps(report, indent=2))

    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
