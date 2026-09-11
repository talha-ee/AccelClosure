import json
import re
from pathlib import Path
from typing import Dict, List

try:
    from .reference_retriever import retrieve
except ImportError:
    from reference_retriever import retrieve


PROJECT_ROOT = Path(__file__).resolve().parents[1]
GEMMINI_ROOT = PROJECT_ROOT / "golden" / "sources" / "gemmini"


FILE_ROUTES = {
    "dataflow": [
        "src/main/scala/gemmini/Dataflow.scala",
        "src/main/scala/gemmini/PE.scala",
        "src/main/scala/gemmini/MeshWithDelays.scala",
    ],

    "array": [
        "src/main/scala/gemmini/PE.scala",
        "src/main/scala/gemmini/Tile.scala",
        "src/main/scala/gemmini/Mesh.scala",
        "src/main/scala/gemmini/MeshWithDelays.scala",
    ],

    "config": [
        "src/main/scala/gemmini/GemminiConfigs.scala",
        "src/main/scala/gemmini/Configs.scala",
    ],

    "memory": [
        "src/main/scala/gemmini/Scratchpad.scala",
        "src/main/scala/gemmini/AccumulatorMem.scala",
        "src/main/scala/gemmini/GemminiConfigs.scala",
    ],

    "matmul": [
        "src/main/scala/gemmini/LoopMatmul.scala",
        "src/main/scala/gemmini/Mesh.scala",
    ],

    "conv": [
        "src/main/scala/gemmini/LoopConv.scala",
        "src/main/scala/gemmini/Mesh.scala",
    ],

    "precision": [
        "src/main/scala/gemmini/Arithmetic.scala",
        "src/main/scala/gemmini/PE.scala",
        "src/main/scala/gemmini/GemminiConfigs.scala",
        "src/main/scala/gemmini/Configs.scala",
    ],

    "pipeline": [
        "src/main/scala/gemmini/Mesh.scala",
        "src/main/scala/gemmini/MeshWithDelays.scala",
        "src/main/scala/gemmini/GemminiConfigs.scala",
    ],
}


ANCHORS = {
    "Dataflow.scala": [
        "object Dataflow",
        "OS, WS, BOTH"
    ],

    "PE.scala": [
        "class MacUnit",
        "class PE[",
        "OUTPUT_STATIONARY",
        "WEIGHT_STATIONARY",
        "Dataflow.OS",
        "Dataflow.WS",
    ],

    "Tile.scala": [
        "class Tile[",
        "Seq.fill(rows, columns)",
    ],

    "Mesh.scala": [
        "class Mesh[",
        "meshRows",
        "meshColumns",
        "new Tile",
    ],

    "MeshWithDelays.scala": [
        "class MeshWithDelays[",
        "Dataflow.OS",
        "Dataflow.WS",
        "new Mesh",
    ],

    "GemminiConfigs.scala": [
        "case class GemminiArrayConfig",
        "tileRows",
        "meshRows",
        "tile_latency",
        "mesh_output_delay",
        "require(inputType.getWidth",
        "require(meshColumns",
        "BLOCK_ROWS",
        "BLOCK_COLS",
    ],

    "Configs.scala": [
        "defaultConfig",
        "inputType =",
        "weightType =",
        "accType =",
        "meshRows =",
        "meshColumns =",
        "dataflow =",
        "sp_capacity",
        "acc_capacity",
    ],

    "Scratchpad.scala": [
        "class Scratchpad",
        "sp_banks",
        "acc_banks",
    ],

    "AccumulatorMem.scala": [
        "class AccumulatorMem",
    ],

    "LoopMatmul.scala": [
        "class LoopMatmul",
        "matmul",
    ],

    "LoopConv.scala": [
        "class LoopConv",
        "conv",
    ],

    "Arithmetic.scala": [
        "trait Arithmetic",
        "object Arithmetic",
    ],
}


def determine_topics(query: str) -> List[str]:
    q = query.lower()

    topics = []

    if any(x in q for x in [
        "ws", "weight-stationary", "weight stationary",
        "os", "output-stationary", "output stationary",
        "dataflow"
    ]):
        topics.append("dataflow")

    if any(x in q for x in [
        "systolic", "array", "mesh", "pe", "tile",
        "16x16", "32x32", "64x64"
    ]):
        topics.append("array")

    if any(x in q for x in [
        "int4", "int8", "int16", "int32",
        "precision", "datatype", "bitwidth"
    ]):
        topics.append("precision")

    if any(x in q for x in [
        "scratchpad", "accumulator", "memory",
        "sram", "buffer"
    ]):
        topics.append("memory")

    if any(x in q for x in [
        "gemm", "matmul", "matrix multiplication"
    ]):
        topics.append("matmul")

    if any(x in q for x in [
        "cnn", "conv", "convolution"
    ]):
        topics.append("conv")

    if any(x in q for x in [
        "pipeline", "latency", "timing", "frequency",
        "mhz", "critical path"
    ]):
        topics.append("pipeline")

    topics.append("config")

    return list(dict.fromkeys(topics))


def select_files(query: str, max_files: int = 7) -> List[str]:
    selected = []

    for topic in determine_topics(query):
        for path in FILE_ROUTES.get(topic, []):
            if path not in selected:
                selected.append(path)

    return selected[:max_files]


def merge_windows(windows):
    if not windows:
        return []

    windows = sorted(windows)
    merged = [list(windows[0])]

    for start, end in windows[1:]:
        last = merged[-1]

        if start <= last[1] + 1:
            last[1] = max(last[1], end)
        else:
            merged.append([start, end])

    return merged


def extract_source(path: Path, context_lines: int = 7,
                   max_windows: int = 5,
                   max_chars: int = 5000) -> Dict:

    lines = path.read_text(errors="replace").splitlines()
    anchors = ANCHORS.get(path.name, [])

    windows = []

    for i, line in enumerate(lines):
        if any(anchor.lower() in line.lower() for anchor in anchors):
            start = max(0, i - context_lines)
            end = min(len(lines), i + context_lines + 1)
            windows.append((start, end))

    windows = merge_windows(windows)[:max_windows]

    if not windows:
        windows = [[0, min(40, len(lines))]]

    excerpts = []
    used_chars = 0

    for start, end in windows:
        numbered = []

        for index in range(start, end):
            numbered.append(f"{index + 1}: {lines[index]}")

        text = "\n".join(numbered)

        remaining = max_chars - used_chars

        if remaining <= 0:
            break

        text = text[:remaining]
        used_chars += len(text)

        excerpts.append({
            "line_start": start + 1,
            "line_end": end,
            "text": text
        })

    return {
        "file": str(path.relative_to(GEMMINI_ROOT)),
        "excerpts": excerpts
    }


def build_context(query: str) -> Dict:
    matches = retrieve(query, top_k=1)

    if not matches:
        return {
            "query": query,
            "status": "NO_GOLDEN_REFERENCE",
            "references": []
        }

    match = matches[0]

    card_path = PROJECT_ROOT / match["card_path"]

    with card_path.open() as f:
        card = json.load(f)

    files = select_files(query)

    source_context = []

    for relative_path in files:
        source_path = GEMMINI_ROOT / relative_path

        if source_path.exists():
            source_context.append(
                extract_source(source_path)
            )

    return {
        "query": query,
        "status": "REFERENCE_FOUND",

        "reference": {
            "id": card["id"],
            "title": card["title"],
            "retrieval_score": match["score"],
            "source": card["source"],
            "reference_status": card["reference_status"]
        },

        "architecture": card["architecture"],

        "architectural_invariants":
            card.get("architectural_invariants", []),

        "agent_instruction":
            card.get("agent_instruction", ""),

        "selected_topics":
            determine_topics(query),

        "selected_source_files":
            files,

        "source_context":
            source_context
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Build source-grounded AccelClosure context."
    )

    parser.add_argument("query")

    parser.add_argument(
        "--output",
        help="Optional output JSON file"
    )

    args = parser.parse_args()

    context = build_context(args.query)

    output = json.dumps(context, indent=2)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output)
        print(f"CONTEXT_WRITTEN={output_path}")
    else:
        print(output)
