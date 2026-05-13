#!/usr/bin/env python3
"""
Run weighted_algo in ORDERED mode on SYNTHETIC graph with different part selection
methods, repeated 50 times with different random seeds.

For each seed and part selection method, extract sortedness metrics and aggregate
statistics across all runs.

Output: CSV files with per-run metrics and aggregated statistics for each part selection method.
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


PART_SELECTION_METHODS = [
    "max_vertices",
    "min_avg_weight",
    "min_first_edge",
    "min_vertices",
]


SUMMARY_FIELDS = [
    "run",
    "seed",
    "part_selection",
    "count",
    "inversion_count",
    "run_count",
    "mean_weight",
]


AGGREGATE_FIELDS = [
    "part_selection",
    "reps",
    "count_mean",
    "count_std",
    "count_min",
    "count_max",
    "inversion_count_mean",
    "inversion_count_std",
    "inversion_count_min",
    "inversion_count_max",
    "run_count_mean",
    "run_count_std",
    "run_count_min",
    "run_count_max",
    "mean_weight_mean",
    "mean_weight_std",
    "mean_weight_min",
    "mean_weight_max",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run weighted_algo on SYNTHETIC graph multiple times with different "
            "part selection methods and random seeds."
        )
    )
    parser.add_argument(
        "--input",
        default="tests_random/SYNTHETIC.txt",
        help="Input partition file (default: tests_random/SYNTHETIC.txt).",
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
        default=50,
        help="Number of repetitions per part selection method (default: 50).",
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
        help="Optional max rows per mode (default: 0).",
    )
    parser.add_argument(
        "--part-selection",
        nargs="+",
        default=PART_SELECTION_METHODS,
        help=f"Part selection methods to test (default: {' '.join(PART_SELECTION_METHODS)}).",
    )
    parser.add_argument(
        "--output-summary",
        default="weighted_randomized_part_selection_summary.csv",
        help="CSV file with per-run metrics.",
    )
    parser.add_argument(
        "--output-aggregate",
        default="weighted_randomized_part_selection_aggregate.csv",
        help="CSV file with aggregated statistics per part selection method.",
    )
    parser.add_argument(
        "--temp-dir",
        default=None,
        help="Directory for temporary CSVs (default: auto-created temporary directory).",
    )
    return parser.parse_args()


def run_cmd(cmd: list[str], label: str) -> subprocess.CompletedProcess[str]:
    """Run command and return result, or exit on failure."""
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.stderr.write(
            f"[run_weighted_randomized_part_selection] command failed ({label}): {' '.join(cmd)}\n"
        )
        if proc.stdout:
            sys.stderr.write(proc.stdout)
        if proc.stderr:
            sys.stderr.write(proc.stderr)
        raise SystemExit(proc.returncode)
    return proc


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    """Read CSV file and return list of row dictionaries."""
    with path.open("r", encoding="ascii", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader)


def to_float(value: str) -> float:
    """Convert string to float, defaulting to 0.0 if empty."""
    return float(value) if value not in (None, "") else 0.0


def to_int(value: str) -> int:
    """Convert string to int, defaulting to 0 if empty."""
    return int(value) if value not in (None, "") else 0


def extract_ordered_metrics(path: Path) -> dict[str, str]:
    """Extract metrics for ORDERED mode from analyze_sortedness output."""
    rows = read_csv_rows(path)
    for row in rows:
        if row.get("mode", "").strip() == "ordered":
            return row
    raise SystemExit(f"[run_weighted_randomized_part_selection] no 'ordered' mode in {path}")


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    """Write list of dicts to CSV file."""
    with path.open("w", encoding="ascii", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def summarize_numeric(values: list[float]) -> tuple[float, float, float, float]:
    """Return mean, std, min, max of values."""
    if not values:
        return 0.0, 0.0, 0.0, 0.0
    mean = statistics.fmean(values)
    std = statistics.stdev(values) if len(values) > 1 else 0.0
    return mean, std, min(values), max(values)


def main() -> None:
    args = parse_args()
    
    if args.reps <= 0:
        raise SystemExit("[run_weighted_randomized_part_selection] --reps must be > 0.")
    if args.max_rows_per_mode < 0:
        raise SystemExit("[run_weighted_randomized_part_selection] --max-rows-per-mode must be >= 0.")

    input_path = Path(args.input)
    if not input_path.is_file():
        raise SystemExit(f"[run_weighted_randomized_part_selection] input file not found: {input_path}")

    weighted_binary = Path(args.weighted_binary)
    if not weighted_binary.is_absolute():
        weighted_binary = (Path.cwd() / weighted_binary).resolve()

    analyzer = Path(args.analyzer)
    if not analyzer.is_absolute():
        analyzer = (Path.cwd() / analyzer).resolve()

    if args.temp_dir is None:
        temp_dir_ctx = tempfile.TemporaryDirectory(prefix="weighted_randomized_part_selection_")
        temp_dir = Path(temp_dir_ctx.name)
    else:
        temp_dir = Path(args.temp_dir)
        temp_dir.mkdir(parents=True, exist_ok=True)
        temp_dir_ctx = None

    base_seed = args.seed if args.seed is not None else random.SystemRandom().randrange(1, 2**31 - 1)

    all_runs: list[dict[str, object]] = []
    metrics_by_method: dict[str, list[dict[str, str]]] = defaultdict(list)

    try:
        for run_index in range(args.reps):
            seed = base_seed + run_index
            sys.stdout.write(f"Run {run_index + 1}/{args.reps} (seed={seed}): Testing all part selection methods\n")
            sys.stdout.flush()

            for part_selection in args.part_selection:
                run_label = f"run_{run_index + 1:03d}_{part_selection}"
                weighted_csv = temp_dir / f"{run_label}.csv"
                summary_csv = temp_dir / f"{run_label}_summary.csv"

                # Build weighted_algo command
                if args.time_limit is None:
                    cmd = [
                        str(weighted_binary),
                        str(input_path),
                        "ordered",
                        str(weighted_csv),
                        str(seed),
                        "0",
                        part_selection,
                    ]
                else:
                    cmd = [
                        str(weighted_binary),
                        str(input_path),
                        str(args.time_limit),
                        str(weighted_csv),
                        str(seed),
                        "ordered",
                        "0",
                        part_selection,
                    ]

                run_cmd(cmd, run_label)

                # Run analyzer
                run_cmd(
                    [
                        args.python,
                        str(analyzer),
                        "--input",
                        str(weighted_csv),
                        "--output",
                        str(summary_csv),
                        "--max-rows-per-mode",
                        str(args.max_rows_per_mode),
                    ],
                    run_label,
                )

                # Extract metrics
                row = extract_ordered_metrics(summary_csv)
                metrics_by_method[part_selection].append(row)
                all_runs.append(
                    {
                        "run": run_index + 1,
                        "seed": seed,
                        "part_selection": part_selection,
                        "count": to_int(row["count"]),
                        "inversion_count": to_int(row["inversion_count"]),
                        "run_count": to_int(row["run_count"]),
                        "mean_weight": to_float(row["mean_weight"]),
                    }
                )

    finally:
        if temp_dir_ctx is not None:
            temp_dir_ctx.cleanup()

    # Write per-run summary
    write_csv(Path(args.output_summary), SUMMARY_FIELDS, all_runs)
    sys.stdout.write(f"Wrote per-run metrics to {args.output_summary}\n")

    # Aggregate statistics
    aggregate_rows: list[dict[str, object]] = []
    for part_selection in args.part_selection:
        metrics = metrics_by_method[part_selection]
        if not metrics:
            continue

        # Collect all values for each metric
        counts = [to_int(m["count"]) for m in metrics]
        inversion_counts = [to_int(m["inversion_count"]) for m in metrics]
        run_counts = [to_int(m["run_count"]) for m in metrics]
        mean_weights = [to_float(m["mean_weight"]) for m in metrics]

        # Compute statistics
        count_mean, count_std, count_min, count_max = summarize_numeric(counts)
        (
            inversion_count_mean,
            inversion_count_std,
            inversion_count_min,
            inversion_count_max,
        ) = summarize_numeric(inversion_counts)
        (
            run_count_mean,
            run_count_std,
            run_count_min,
            run_count_max,
        ) = summarize_numeric(run_counts)
        (
            mean_weight_mean,
            mean_weight_std,
            mean_weight_min,
            mean_weight_max,
        ) = summarize_numeric(mean_weights)

        aggregate_rows.append(
            {
                "part_selection": part_selection,
                "reps": len(metrics),
                "count_mean": count_mean,
                "count_std": count_std,
                "count_min": count_min,
                "count_max": count_max,
                "inversion_count_mean": inversion_count_mean,
                "inversion_count_std": inversion_count_std,
                "inversion_count_min": inversion_count_min,
                "inversion_count_max": inversion_count_max,
                "run_count_mean": run_count_mean,
                "run_count_std": run_count_std,
                "run_count_min": run_count_min,
                "run_count_max": run_count_max,
                "mean_weight_mean": mean_weight_mean,
                "mean_weight_std": mean_weight_std,
                "mean_weight_min": mean_weight_min,
                "mean_weight_max": mean_weight_max,
            }
        )

    # Write aggregate statistics
    write_csv(Path(args.output_aggregate), AGGREGATE_FIELDS, aggregate_rows)
    sys.stdout.write(f"Wrote aggregated statistics to {args.output_aggregate}\n")

    sys.stdout.write("Done!\n")


if __name__ == "__main__":
    main()
