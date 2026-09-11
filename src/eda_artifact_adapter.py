import argparse
import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def adapt_yosys_netlist(
    source: Path,
    output: Path,
    backup: Path,
    report_path: Path,
):
    if not source.exists():
        raise FileNotFoundError(source)

    original = source.read_text()

    # Conservative adapter:
    # remove Verilog "signed" qualifiers only from structural
    # input/output/wire declarations.
    #
    # This exists specifically for the verified Yosys -> OpenROAD
    # parser interoperability issue observed in the Sky130 flow.
    pattern = (
        r'^(\s*(?:input|output|wire)\s+)'
        r'signed\s+'
    )

    adapted, count = re.subn(
        pattern,
        r'\1',
        original,
        flags=re.MULTILINE,
    )

    output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    backup.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    report_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    shutil.copy2(
        source,
        backup,
    )

    output.write_text(adapted)

    report = {
        "adapter": "AccelClosure EDA Artifact Adapter",
        "adapter_version": "1.0",
        "timestamp_utc":
            datetime.now(timezone.utc).isoformat(),
        "failure_class": "EDA_INTEROPERABILITY",
        "interface": "Yosys -> OpenROAD",
        "transformation": (
            "Remove signed qualifiers from structural "
            "input/output/wire declarations"
        ),
        "source": str(source),
        "backup": str(backup),
        "output": str(output),
        "source_sha256": sha256(source),
        "output_sha256": sha256(output),
        "signed_declarations_removed": count,
        "rtl_modified": False,
        "mapped_cell_logic_modified": False,
        "requires_openroad_revalidation": True,
    }

    report_path.write_text(
        json.dumps(
            report,
            indent=2,
        )
    )

    print(
        json.dumps(
            report,
            indent=2,
        )
    )


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--source",
        required=True,
    )

    parser.add_argument(
        "--output",
        required=True,
    )

    parser.add_argument(
        "--backup",
        required=True,
    )

    parser.add_argument(
        "--report",
        required=True,
    )

    args = parser.parse_args()

    adapt_yosys_netlist(
        Path(args.source),
        Path(args.output),
        Path(args.backup),
        Path(args.report),
    )


if __name__ == "__main__":
    main()
