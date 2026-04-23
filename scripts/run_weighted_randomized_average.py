#!/usr/bin/env python3
"""Repeat weighted sortedness analysis on one input with fresh random weights.

The weighted solver assigns random weights only when coordinates are missing.
This runner repeats the same input multiple times with different seeds, keeps the
same weight matrix across non_ordered / sorted_at_end / ordered within each run,
and aggregates both the per-run sortedness metrics and the per-rank weight
sequences.
"""

from __future__ import annotations

import argparse
import csv
import random
import statistics
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path


PART_SELECTION_ALIASES = {
    "first": None,
    "default": None,
    "max_vertices": "max_vertices",
    "min_avg_weight": "min_avg_weight",
    "min_first_edge": "min_first_edge",
    "min_vertices": "min_vertices",
}


SUMMARY_FIELDS = [
    "run",
    "seed",
    "input_file",
    "mode",
    "count",
    "inversion_count",
    "normalized_kendall_tau",
    "run_count",
    "lis_ratio",
    "mean_abs_delta",
    "mean_weight",
]


AGGREGATE_FIELDS = [
    "input_file",
    "mode",
    "reps",
    "count_mean",
    "count_std",
    "count_min",
    "count_max",
    "inversion_count_mean",
    "inversion_count_std",
    "inversion_count_min",
    "inversion_count_max",
    "normalized_kendall_tau_mean",
    "normalized_kendall_tau_std",
    "normalized_kendall_tau_min",
    "normalized_kendall_tau_max",
    "run_count_mean",
    "run_count_std",
    "run_count_min",
    "run_count_max",
    "lis_ratio_mean",
    "lis_ratio_std",
    "lis_ratio_min",
    "lis_ratio_max",
    "mean_abs_delta_mean",
    "mean_abs_delta_std",
    "mean_abs_delta_min",
    "mean_abs_delta_max",
    "mean_weight_mean",
    "mean_weight_std",
    "mean_weight_min",
    "mean_weight_max",
]


RANK_AVERAGE_FIELDS = [
    "input_file",
    "mode",
    "rank",
    "reps",
    "mean_total_weight",
    "std_total_weight",
    "min_total_weight",
    "max_total_weight",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Repeat weighted_algo on one input with different random seeds and aggregate metrics."
        )
    )
    parser.add_argument(
        "input_file",
        help="Input partition file to test (for example tests_article/6Comp18Ver_diffnumver.txt).",
    )
    parser.add_argument(
        "--weighted-binary",
        default="./weighted_algo",
        help="Path to the weighted_algo binary (default: ./weighted_algo).",
    )
    parser.add_argument(
        "--analyzer",
        default="scripts/analyze_sortedness.py",
        help="Path to analyze_sortedness.py (default: scripts/analyze_sortedness.py).",
    )
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="Python executable used for the analyzer (default: current interpreter).",
    )
    parser.add_argument(
        "--reps",
        type=int,
        default=100,
        help="Number of repetitions to run (default: 100).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Optional base seed. Each repetition uses seed + run index.",
    )
    parser.add_argument(
        "--time-limit",
        type=float,
        default=None,
        help="Optional time limit passed to weighted_algo.",
    )
    parser.add_argument(
        "--max-rows-per-mode",
        type=int,
        default=0,
        help="Optional max rows per mode passed to weighted_algo/analyzer (default: 0).",
    )
    parser.add_argument(
        "--part-selection",
        default="default",
        choices=sorted(PART_SELECTION_ALIASES),
        help=(
            "Part selection method for ordered mode. "
            "Use 'default' to keep weighted_algo internal default heuristic."
        ),
    )
    parser.add_argument(
        "--output-summary",
        default="weighted_randomized_average_summary.csv",
        help="CSV file with per-run metrics and aggregate statistics.",
    )
    parser.add_argument(
        "--output-rank-average",
        default="",
        help="Optional CSV file with per-rank average weights across repetitions.",
    )
    parser.add_argument(
        "--output-raw",
        default="weighted_randomized_average_runs.csv",
        help="CSV file with one row per run and mode.",
    )
    parser.add_argument(
        "--temp-dir",
        default=None,
        help="Directory for temporary CSVs (default: auto-created temporary directory).",
    )
    return parser.parse_args()


def run_cmd(cmd: list[str], label: str) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.stderr.write(f"[run_weighted_randomized_average] command failed ({label}): {' '.join(cmd)}\n")
        if proc.stdout:
            sys.stderr.write(proc.stdout)
        if proc.stderr:
            sys.stderr.write(proc.stderr)
        raise SystemExit(proc.returncode)
    return proc


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="ascii", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader)


def load_sequence_rows(path: Path) -> dict[str, list[float]]:
    sequences: dict[str, list[float]] = defaultdict(list)
    with path.open("r", encoding="ascii", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or {"mode", "rank", "total_weight"} - set(reader.fieldnames):
            raise SystemExit(f"[run_weighted_randomized_average] invalid weighted CSV header in {path}.")
        for row in reader:
            sequences[row["mode"].strip()].append(float(row["total_weight"]))
    return dict(sequences)


def to_float(value: str) -> float:
    return float(value) if value not in (None, "") else 0.0


def to_int(value: str) -> int:
    return int(value) if value not in (None, "") else 0


def extract_summary_row(path: Path) -> dict[str, dict[str, str]]:
    rows = read_csv_rows(path)
    by_mode: dict[str, dict[str, str]] = {}
    for row in rows:
        mode = row.get("mode", "").strip()
        if mode:
            by_mode[mode] = row
    required = {"non_ordered", "sorted_at_end", "ordered"}
    missing = required - set(by_mode)
    if missing:
        raise SystemExit(f"[run_weighted_randomized_average] missing modes in {path}: {', '.join(sorted(missing))}.")
    return by_mode


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="ascii", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def summarize_numeric(values: list[float]) -> tuple[float, float, float, float]:
    if not values:
        return 0.0, 0.0, 0.0, 0.0
    mean = statistics.fmean(values)
    std = statistics.stdev(values) if len(values) > 1 else 0.0
    return mean, std, min(values), max(values)


def main() -> None:
    args = parse_args()
    if args.reps <= 0:
        raise SystemExit("[run_weighted_randomized_average] --reps must be > 0.")
    if args.max_rows_per_mode < 0:
        raise SystemExit("[run_weighted_randomized_average] --max-rows-per-mode must be >= 0.")

    input_path = Path(args.input_file)
    if not input_path.is_file():
        raise SystemExit(f"[run_weighted_randomized_average] input file not found: {input_path}")

    weighted_binary = Path(args.weighted_binary)
    if not weighted_binary.is_absolute():
        weighted_binary = (Path.cwd() / weighted_binary).resolve()

    analyzer = Path(args.analyzer)
    if not analyzer.is_absolute():
        analyzer = (Path.cwd() / analyzer).resolve()

    if args.temp_dir is None:
        temp_dir_ctx = tempfile.TemporaryDirectory(prefix="weighted_randomized_average_")
        temp_dir = Path(temp_dir_ctx.name)
    else:
        temp_dir = Path(args.temp_dir)
        temp_dir.mkdir(parents=True, exist_ok=True)
        temp_dir_ctx = None

    base_seed = args.seed if args.seed is not None else random.SystemRandom().randrange(1, 2**31 - 1)
    normalized_part_selection = PART_SELECTION_ALIASES[args.part_selection]

    raw_rows: list[dict[str, object]] = []
    per_mode_metrics: dict[str, list[dict[str, str]]] = defaultdict(list)
    collect_rank_average = bool(args.output_rank_average)
    per_mode_rank_weights: dict[str, dict[int, list[float]]] = defaultdict(lambda: defaultdict(list))

    try:
        for run_index in range(args.reps):
            seed = base_seed + run_index
            run_label = f"run_{run_index + 1:03d}"
            weighted_csv = temp_dir / f"{run_label}.csv"
            summary_csv = temp_dir / f"{run_label}_summary.csv"

            if args.time_limit is None:
                cmd = [
                    str(weighted_binary),
                    str(input_path),
                    "all",
                    str(weighted_csv),
                    str(seed),
                    "0",
                ]
            else:
                cmd = [
                    str(weighted_binary),
                    str(input_path),
                    str(args.time_limit),
                    str(weighted_csv),
                    str(seed),
                    "all",
                    "0",
                ]

            if normalized_part_selection is not None:
                cmd.append(normalized_part_selection)

            run_cmd(cmd, run_label)
            run_cmd([
                args.python,
                str(analyzer),
                "--input",
                str(weighted_csv),
                "--output",
                str(summary_csv),
                "--max-rows-per-mode",
                str(args.max_rows_per_mode),
            ], run_label)

            summary_by_mode = extract_summary_row(summary_csv)
            sequence_rows = load_sequence_rows(weighted_csv) if collect_rank_average else {}

            for mode in ("non_ordered", "sorted_at_end", "ordered"):
                row = summary_by_mode[mode]
                per_mode_metrics[mode].append(row)
                raw_rows.append(
                    {
                        "run": run_index + 1,
                        "seed": seed,
                        "input_file": str(input_path),
                        "mode": mode,
                        "count": to_int(row["count"]),
                        "inversion_count": to_int(row["inversion_count"]),
                        "normalized_kendall_tau": to_float(row["normalized_kendall_tau"]),
                        "run_count": to_int(row["run_count"]),
                        "lis_ratio": to_float(row["lis_ratio"]),
                        "mean_abs_delta": to_float(row["mean_abs_delta"]),
                        "mean_weight": to_float(row["mean_weight"]),
                    }
                )

                for rank, weight in enumerate(sequence_rows.get(mode, []), start=1):
                    per_mode_rank_weights[mode][rank].append(weight)

    finally:
        if temp_dir_ctx is not None:
            temp_dir_ctx.cleanup()

    aggregate_rows: list[dict[str, object]] = []
    for mode in ("non_ordered", "sorted_at_end", "ordered"):
        rows = per_mode_metrics[mode]
        if not rows:
            continue

        numeric_fields = [
            "count",
            "inversion_count",
            "normalized_kendall_tau",
            "run_count",
            "lis_ratio",
            "mean_abs_delta",
            "mean_weight",
        ]

        aggregate: dict[str, object] = {
            "input_file": str(input_path),
            "mode": mode,
            "reps": len(rows),
        }

        for field in numeric_fields:
            values = [to_float(row[field]) for row in rows]
            mean, std, min_value, max_value = summarize_numeric(values)
            aggregate[f"{field}_mean"] = mean
            aggregate[f"{field}_std"] = std
            aggregate[f"{field}_min"] = min_value
            aggregate[f"{field}_max"] = max_value

        aggregate_rows.append(aggregate)

    rank_rows: list[dict[str, object]] = []
    if collect_rank_average:
        for mode in ("non_ordered", "sorted_at_end", "ordered"):
            for rank in sorted(per_mode_rank_weights[mode]):
                values = per_mode_rank_weights[mode][rank]
                mean, std, min_value, max_value = summarize_numeric(values)
                rank_rows.append(
                    {
                        "input_file": str(input_path),
                        "mode": mode,
                        "rank": rank,
                        "reps": len(values),
                        "mean_total_weight": mean,
                        "std_total_weight": std,
                        "min_total_weight": min_value,
                        "max_total_weight": max_value,
                    }
                )

    write_csv(Path(args.output_raw), SUMMARY_FIELDS, raw_rows)
    write_csv(Path(args.output_summary), AGGREGATE_FIELDS, aggregate_rows)
    if collect_rank_average:
        write_csv(Path(args.output_rank_average), RANK_AVERAGE_FIELDS, rank_rows)

    sys.stderr.write(
        f"[run_weighted_randomized_average] wrote {len(raw_rows)} raw rows, {len(aggregate_rows)} aggregate rows, and {len(rank_rows)} rank rows.\n"
    )


if __name__ == "__main__":
    main()