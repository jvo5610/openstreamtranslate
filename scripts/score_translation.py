#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path

try:
    from scripts.score_asr import srt_text
except ModuleNotFoundError:
    from score_asr import srt_text


def normalized_text(text: str) -> str:
    text = unicodedata.normalize("NFC", text.lower())
    return " ".join(re.findall(r"[^\W_]+(?:'[^\W_]+)?", text, flags=re.UNICODE))


def token_f1(reference: str, hypothesis: str) -> float:
    expected = Counter(reference.split())
    actual = Counter(hypothesis.split())
    overlap = sum((expected & actual).values())
    if not expected or not actual:
        return 0.0
    precision = overlap / sum(actual.values())
    recall = overlap / sum(expected.values())
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


def ngrams(text: str, order: int) -> Counter[str]:
    compact = text.replace(" ", "")
    return Counter(compact[index:index + order] for index in range(len(compact) - order + 1))


def chrf(reference: str, hypothesis: str, beta: float = 2.0, max_order: int = 6) -> float:
    precisions: list[float] = []
    recalls: list[float] = []
    beta_squared = beta * beta
    for order in range(1, max_order + 1):
        expected = ngrams(reference, order)
        actual = ngrams(hypothesis, order)
        if not expected or not actual:
            continue
        overlap = sum((expected & actual).values())
        precisions.append(overlap / sum(actual.values()))
        recalls.append(overlap / sum(expected.values()))
    if not precisions:
        return 0.0
    precision = sum(precisions) / len(precisions)
    recall = sum(recalls) / len(recalls)
    denominator = beta_squared * precision + recall
    return (
        (1 + beta_squared) * precision * recall / denominator
        if denominator else 0.0
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("reference", type=Path)
    parser.add_argument("hypothesis", type=Path)
    parser.add_argument("--json-field", default="translation")
    parser.add_argument("--start-seconds", type=float, default=0)
    parser.add_argument("--end-seconds", type=float)
    args = parser.parse_args()

    reference = normalized_text(srt_text(args.reference, args.start_seconds, args.end_seconds))
    raw = args.hypothesis.read_text(encoding="utf-8")
    if args.hypothesis.suffix == ".json":
        raw = json.loads(raw)[args.json_field]
    hypothesis = normalized_text(raw)
    result = {
        "reference_words": len(reference.split()),
        "hypothesis_words": len(hypothesis.split()),
        "length_ratio": round(len(hypothesis.split()) / max(1, len(reference.split())), 4),
        "token_f1": round(token_f1(reference, hypothesis), 4),
        "chrf": round(chrf(reference, hypothesis), 4),
    }
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
