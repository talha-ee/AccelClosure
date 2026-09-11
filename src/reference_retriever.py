import json
import re
from pathlib import Path
from typing import Dict, List, Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CARDS_DIR = PROJECT_ROOT / "golden" / "knowledge" / "cards"


STOP_WORDS = {
    "a", "an", "and", "the", "to", "for", "of", "in", "on",
    "with", "using", "use", "design", "designing", "selecting",
    "changing", "reasoning", "about"
}


SYNONYMS = {
    "ws": {"weight", "stationary", "weight_stationary"},
    "weight_stationary": {"ws", "weight", "stationary"},
    "os": {"output", "stationary", "output_stationary"},
    "output_stationary": {"os", "output", "stationary"},
    "systolic": {"array", "mesh"},
    "gemm": {"matmul", "matrix", "multiplication"},
    "matmul": {"gemm", "matrix", "multiplication"},
    "precision": {"int8", "int16", "datatype", "arithmetic"},
    "memory": {"scratchpad", "accumulator", "sram"},
}


def tokenize(text: str) -> set[str]:
    tokens = {
        t for t in re.findall(r"[a-zA-Z0-9_]+", text.lower())
        if t not in STOP_WORDS
    }

    expanded = set(tokens)

    for token in list(tokens):
        expanded.update(SYNONYMS.get(token, set()))

    return expanded


def flatten_card(card: Dict[str, Any]) -> str:
    searchable_parts = [
        card.get("id", ""),
        card.get("title", ""),
        card.get("architecture", {}).get("type", ""),
        " ".join(card.get("architecture", {}).get("hierarchy", [])),
        " ".join(card.get("architecture", {}).get("supported_dataflows", [])),
        " ".join(card.get("search_space", {}).get("parameters", [])),
        " ".join(card.get("retrieve_when", [])),
        card.get("agent_instruction", "")
    ]

    return " ".join(searchable_parts)


def load_cards() -> List[Dict[str, Any]]:
    cards = []

    for path in sorted(CARDS_DIR.glob("*.json")):
        with path.open() as f:
            card = json.load(f)

        card["_card_path"] = str(path.relative_to(PROJECT_ROOT))
        cards.append(card)

    return cards


def score_card(query: str, card: Dict[str, Any]) -> float:
    query_tokens = tokenize(query)
    card_tokens = tokenize(flatten_card(card))

    if not query_tokens:
        return 0.0

    overlap = query_tokens & card_tokens

    score = len(overlap) / len(query_tokens)

    # Strong bonus if an explicit retrieve_when phrase is highly relevant.
    for condition in card.get("retrieve_when", []):
        condition_tokens = tokenize(condition)

        if not condition_tokens:
            continue

        condition_overlap = query_tokens & condition_tokens
        condition_score = len(condition_overlap) / len(condition_tokens)

        score += 0.5 * condition_score

    return round(score, 4)


def retrieve(query: str, top_k: int = 3) -> List[Dict[str, Any]]:
    results = []

    for card in load_cards():
        score = score_card(query, card)

        if score > 0:
            results.append({
                "id": card["id"],
                "title": card["title"],
                "score": score,
                "card_path": card["_card_path"],
                "source": card.get("source", {}),
                "retrieve_when": card.get("retrieve_when", [])
            })

    results.sort(key=lambda x: x["score"], reverse=True)

    return results[:top_k]


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Retrieve AccelClosure golden references."
    )
    parser.add_argument("query", help="Hardware engineering query")
    parser.add_argument("--top-k", type=int, default=3)

    args = parser.parse_args()

    matches = retrieve(args.query, args.top_k)

    print(json.dumps({
        "query": args.query,
        "matches": matches
    }, indent=2))
