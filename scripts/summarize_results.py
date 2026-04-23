#!/usr/bin/env python3
"""Summarize raw benchmark runs into aggregated timing statistics."""

import argparse
import csv
import statistics
import sys
from collections import defaultdict
from pathlib import Path

RAW_FIELDS = {
    "source",
    "label",
    "input_path",
    "rep",
    "solver_input",
    "num_vertices",
    "num_components",
    "min_component_size",
    "max_component_size",
    "num_trees",
    "elapsed_ms",
    "status",
}

SUMMARY_FIELDS = [
    "source",
    "label",
    "input_path",
    "solver_input",
    "reps",
    "status_ok",
    "status_timeout",
    "status_other",
    "num_vertices",
    "num_components",
    "min_component_size",
    "max_component_size",
    "num_trees_mean",
    "num_trees_std",
    "num_trees_min",
    "num_trees_max",
    "mean_ms",
    "std_ms",
    "median_ms",
    "min_ms",
    "max_ms",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Aggregate repeated opti_algo runs into summary statistics."
    )
    parser.add_argument(
        "--input",
        default="results.csv",
        help="CSV file produced by run_bench.py (default: results.csv).",
    )
    parser.add_argument(
        "--output",
        default="results_summary.csv",
        help="Destination CSV for aggregated statistics (default: results_summary.csv).",
    )
    return parser.parse_args()


def read_rows(path: str) -> list[dict]:
    csv_path = Path(path)
    if not csv_path.is_file():
        sys.stderr.write(f"[summarize_results] input file '{path}' not found.\n")
        sys.exit(1)

    rows: list[dict] = []
    with csv_path.open("r", encoding="ascii", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            sys.stderr.write(f"[summarize_results] '{path}' has no header.\n")
            sys.exit(1)
        missing = RAW_FIELDS - set(reader.fieldnames)
        if missing:
            sys.stderr.write(
                f"[summarize_results] missing columns in '{path}': {', '.join(sorted(missing))}.\n"
            )
            sys.exit(1)

        for line_no, raw in enumerate(reader, start=2):
            try:
                row = {
                    "source": raw["source"],
                    "label": raw["label"],
                    "input_path": raw["input_path"],
                    "solver_input": raw["solver_input"],
                    "num_vertices": int(raw["num_vertices"]),
                    "num_components": int(raw["num_components"]),
                    "min_component_size": int(raw["min_component_size"]),
                    "max_component_size": int(raw["max_component_size"]),
                    "num_trees": int(raw["num_trees"]),
                    "elapsed_ms": float(raw["elapsed_ms"]),
                    "status": raw["status"],
                }
            except ValueError as err:
                sys.stderr.write(
                    f"[summarize_results] parse error line {line_no} in '{path}': {err}.\n"
                )
                sys.exit(1)
            rows.append(row)

    if not rows:
        sys.stderr.write(f"[summarize_results] '{path}' contains no data rows.\n")
        sys.exit(1)
    return rows


def ensure_constant(field: str, items: list[dict], key: tuple[str, ...]) -> int:
    values = {item[field] for item in items}
    if len(values) != 1:
        sys.stderr.write(
            f"[summarize_results] inconsistent '{field}' for group {key}: {sorted(values)}.\n"
        )
        sys.exit(1)
    return values.pop()


def summarize(rows: list[dict]) -> list[dict]:
    grouped: defaultdict[tuple[str, str, str, str], list[dict]] = defaultdict(list)
    for row in rows:
        grouped[
            (row["source"], row["label"], row["input_path"], row["solver_input"])
        ].append(row)

    summaries: list[dict] = []
    for key in sorted(grouped):
        items = grouped[key]
        times = [item["elapsed_ms"] for item in items]
        tree_counts = [item["num_trees"] for item in items]
        assert times

        status_counts = defaultdict(int)
        for item in items:
            status_counts[item["status"]] += 1

        summary = {
            "source": key[0],
            "label": key[1],
            "input_path": key[2],
            "solver_input": key[3],
            "reps": len(items),
            "status_ok": status_counts.get("ok", 0),
            "status_timeout": status_counts.get("timeout", 0),
            "status_other": len(items)
            - status_counts.get("ok", 0)
            - status_counts.get("timeout", 0),
            "num_vertices": ensure_constant("num_vertices", items, key),
            "num_components": ensure_constant("num_components", items, key),
            "min_component_size": ensure_constant("min_component_size", items, key),
            "max_component_size": ensure_constant("max_component_size", items, key),
            "num_trees_mean": statistics.fmean(tree_counts),
            "num_trees_std": statistics.stdev(tree_counts) if len(tree_counts) > 1 else 0.0,
            "num_trees_min": min(tree_counts),
            "num_trees_max": max(tree_counts),
            "mean_ms": statistics.fmean(times),
            "std_ms": statistics.stdev(times) if len(times) > 1 else 0.0,
            "median_ms": statistics.median(times),
            "min_ms": min(times),
            "max_ms": max(times),
        }
        summaries.append(summary)
    return summaries


def write_summary(rows: list[dict], output_path: str) -> None:
    with open(output_path, "w", encoding="ascii", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SUMMARY_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    **row,
                    "num_trees_mean": f"{row['num_trees_mean']:.6f}",
                    "num_trees_std": f"{row['num_trees_std']:.6f}",
                    "num_trees_min": f"{row['num_trees_min']:.6f}",
                    "num_trees_max": f"{row['num_trees_max']:.6f}",
                    "mean_ms": f"{row['mean_ms']:.6f}",
                    "std_ms": f"{row['std_ms']:.6f}",
                    "median_ms": f"{row['median_ms']:.6f}",
                    "min_ms": f"{row['min_ms']:.6f}",
                    "max_ms": f"{row['max_ms']:.6f}",
                }
            )


def main() -> None:
    args = parse_args()
    rows = read_rows(args.input)
    summaries = summarize(rows)
    write_summary(summaries, args.output)
    sys.stderr.write(
        f"[summarize_results] wrote {len(summaries)} aggregated row(s) to {args.output}.\n"
    )


if __name__ == "__main__":
    main()
