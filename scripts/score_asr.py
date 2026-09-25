#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path


def timestamp_seconds(value: str) -> float:
    hours, minutes, seconds = value.strip().replace(",", ".").split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def srt_text(path: Path, start_seconds: float = 0, end_seconds: float | None = None) -> str:
    blocks = re.split(r"\n\s*\n", path.read_text(encoding="utf-8-sig").strip())
    lines: list[str] = []
    for block in blocks:
        block_lines = [line.strip() for line in block.splitlines()]
        timing = next((index for index, line in enumerate(block_lines) if "-->" in line), None)
        if timing is not None:
            starts_at, ends_at = (part.strip() for part in block_lines[timing].split("-->", 1))
            if timestamp_seconds(ends_at) <= start_seconds:
                continue
            if end_seconds is not None and timestamp_seconds(starts_at) >= end_seconds:
                continue
            lines.extend(block_lines[timing + 1 :])
    return " ".join(lines)


def normalize(text: str) -> list[str]:
    text = unicodedata.normalize("NFD", text.lower())
    text = "".join(char for char in text if unicodedata.category(char) != "Mn")
    return re.findall(r"[a-z0-9]+(?:'[a-z0-9]+)?", text)


def distance(reference: list[str], hypothesis: list[str]) -> int:
    previous = list(range(len(hypothesis) + 1))
    for row, expected in enumerate(reference, 1):
        current = [row]
        for column, actual in enumerate(hypothesis, 1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[column] + 1,
                    previous[column - 1] + (expected != actual),
                )
            )
        previous = current
    return previous[-1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("reference", type=Path)
    parser.add_argument("hypothesis", type=Path)
    parser.add_argument("--json-field", default="text")
    parser.add_argument("--start-seconds", type=float, default=0)
    parser.add_argument("--end-seconds", type=float)
    args = parser.parse_args()

    expected = normalize(srt_text(args.reference, args.start_seconds, args.end_seconds))
    raw = args.hypothesis.read_text(encoding="utf-8")
    if args.hypothesis.suffix == ".json":
        raw = json.loads(raw)[args.json_field]
    actual = normalize(raw)
    errors = distance(expected, actual)
    print(json.dumps({
        "reference_words": len(expected),
        "hypothesis_words": len(actual),
        "word_errors": errors,
        "wer": round(errors / len(expected), 4),
        "accuracy": round(max(0, 1 - errors / len(expected)), 4),
    }))


if __name__ == "__main__":
    main()
