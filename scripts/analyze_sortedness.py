#!/usr/bin/env python3
"""Analyze per-mode sortedness against each mode's own ascending-weight order."""

import argparse
import csv
import sys
from bisect import bisect_left
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path


@dataclass
class SequenceStats:
    count: int
    inversion_count: int
    normalized_kendall_tau: float
    run_count: int
    lis_ratio: float
    mean_abs_delta: float
    mean_weight: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compare each mode sequence against its own ideal ascending order "
            "using sortedness metrics."
        )
    )
    parser.add_argument(
        "--input",
        default="weights_sequences.csv",
        help="CSV produced by weighted_algo (default: weights_sequences.csv).",
    )
    parser.add_argument(
        "--output",
        default="sortedness_summary.csv",
        help="Destination CSV for sortedness metrics (default: sortedness_summary.csv).",
    )
    parser.add_argument(
        "--max-rows-per-mode",
        type=int,
        default=0,
        help=(
            "Optional cap on rows loaded per mode (0 means all rows). "
            "Useful for very large files."
        ),
    )
    return parser.parse_args()


def read_sequences(path: str, max_rows_per_mode: int) -> dict[str, list[float]]:
    csv_path = Path(path)
    if not csv_path.is_file():
        sys.stderr.write(f"[analyze_sortedness] input file '{path}' not found.\n")
        sys.exit(1)

    sequences: dict[str, list[float]] = defaultdict(list)
    with csv_path.open("r", encoding="ascii", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or {"mode", "rank", "total_weight"} - set(reader.fieldnames):
            sys.stderr.write(
                f"[analyze_sortedness] expected columns mode, rank, total_weight in '{path}'.\n"
            )
            sys.exit(1)

        for line_no, row in enumerate(reader, start=2):
            try:
                mode = row["mode"].strip()
                if max_rows_per_mode > 0 and len(sequences[mode]) >= max_rows_per_mode:
                    continue
                weight = float(row["total_weight"])
            except (KeyError, ValueError) as err:
                sys.stderr.write(
                    f"[analyze_sortedness] parse error line {line_no} in '{path}': {err}.\n"
                )
                sys.exit(1)
            sequences[mode].append(weight)

    if not sequences:
        sys.stderr.write(f"[analyze_sortedness] '{path}' contains no data rows.\n")
        sys.exit(1)
    return dict(sequences)


def rank_positions_against_sorted(sequence: list[float]) -> list[int]:
    """Return each element's position in stable ascending order of the same sequence."""
    sorted_indices = sorted(range(len(sequence)), key=lambda idx: (sequence[idx], idx))
    positions = [0] * len(sequence)
    for rank, original_idx in enumerate(sorted_indices):
        positions[original_idx] = rank
    return positions


def inversion_count(values: list[int]) -> int:
    if len(values) < 2:
        return 0

    def merge_count(arr: list[int]) -> tuple[list[int], int]:
        if len(arr) <= 1:
            return arr, 0
        mid = len(arr) // 2
        left, left_inv = merge_count(arr[:mid])
        right, right_inv = merge_count(arr[mid:])
        merged: list[int] = []
        i = j = 0
        inversions = left_inv + right_inv
        while i < len(left) and j < len(right):
            if left[i] <= right[j]:
                merged.append(left[i])
                i += 1
            else:
                merged.append(right[j])
                inversions += len(left) - i
                j += 1
        merged.extend(left[i:])
        merged.extend(right[j:])
        return merged, inversions

    _, total = merge_count(values)
    return total


def run_count(values: list[int]) -> int:
    if not values:
        return 0
    runs = 1
    for prev, curr in zip(values, values[1:]):
        if curr < prev:
            runs += 1
    return runs


def lis_ratio(values: list[int]) -> float:
    if not values:
        return 0.0

    tails: list[int] = []
    for value in values:
        pos = bisect_left(tails, value)
        if pos == len(tails):
            tails.append(value)
        else:
            tails[pos] = value
    return len(tails) / len(values)


def displacement_mean(values: list[int]) -> float:
    if not values:
        return 0.0
    abs_deltas = [abs(index - value) for index, value in enumerate(values)]
    return sum(abs_deltas) / len(values)


def analyze(sequence: list[float]) -> SequenceStats:
    if not sequence:
        return SequenceStats(
            count=0,
            inversion_count=0,
            normalized_kendall_tau=0.0,
            run_count=0,
            lis_ratio=0.0,
            mean_abs_delta=0.0,
            mean_weight=0.0,
        )

    positions = rank_positions_against_sorted(sequence)
    inv = inversion_count(positions)
    runs = run_count(positions)
    lis = lis_ratio(positions)
    mean_abs_delta = displacement_mean(positions)
    mean_weight = sum(sequence) / len(sequence)
    n = len(positions)
    max_inv = (n * (n - 1)) // 2
    tau = (inv / max_inv) if max_inv > 0 else 0.0
    return SequenceStats(
        count=len(sequence),
        inversion_count=inv,
        normalized_kendall_tau=tau,
        run_count=runs,
        lis_ratio=lis,
        mean_abs_delta=mean_abs_delta,
        mean_weight=mean_weight,
    )


def write_summary(rows: list[dict], output_path: str) -> None:
    with open(output_path, "w", encoding="ascii", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "mode",
                "count",
                "inversion_count",
                "normalized_kendall_tau",
                "run_count",
                "lis_ratio",
                "mean_abs_delta",
                "mean_weight",
            ],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main() -> None:
    args = parse_args()
    if args.max_rows_per_mode < 0:
        sys.stderr.write("[analyze_sortedness] --max-rows-per-mode must be >= 0.\n")
        sys.exit(1)

    sequences = read_sequences(args.input, args.max_rows_per_mode)

    output_rows: list[dict] = []

    preferred_mode_order = ["non_ordered", "ordered", "sorted_at_end"]
    modes = [mode for mode in preferred_mode_order if mode in sequences]
    modes.extend(sorted(mode for mode in sequences if mode not in preferred_mode_order))

    for mode in modes:
        stats = analyze(sequences[mode])
        output_rows.append(
            {
                "mode": mode,
                "count": stats.count,
                "inversion_count": stats.inversion_count,
                "normalized_kendall_tau": f"{stats.normalized_kendall_tau:.6f}",
                "run_count": stats.run_count,
                "lis_ratio": f"{stats.lis_ratio:.6f}",
                "mean_abs_delta": f"{stats.mean_abs_delta:.6f}",
                "mean_weight": f"{stats.mean_weight:.12g}",
            }
        )

    write_summary(output_rows, args.output)
    sys.stderr.write(
        f"[analyze_sortedness] wrote {len(output_rows)} row(s) to {args.output}.\n"
    )


if __name__ == "__main__":
    main()