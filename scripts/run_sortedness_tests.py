#!/usr/bin/env python3
"""Run weighted sortedness analysis across multiple test files."""

import argparse
import csv
import subprocess
import sys
from pathlib import Path


SUMMARY_FIELDS = [
    "input_file",
    "status",
    "error_message",
    "mode",
    "count",
    "inversion_count",
    "normalized_kendall_tau",
    "run_count",
    "lis_ratio",
    "mean_abs_delta",
    "mean_weight",
]

COMPARISON_FIELDS = [
    "input_file",
    "status",
    "error_message",
    "non_ordered_count",
    "ordered_count",
    "delta_inversion_count",
    "delta_normalized_kendall_tau",
    "delta_run_count",
    "delta_lis_ratio",
    "delta_mean_abs_delta",
    "non_ordered_mean_weight",
    "ordered_mean_weight",
    "delta_mean_weight",
    "inversion_ord_to_non_ratio",
    "run_excess_ord_to_non_ratio",
    "non_ordered_inv_over_max",
    "ordered_inv_over_max",
    "non_ordered_run_over_max",
    "ordered_run_over_max",
    "inversion_reduction_pct",
    "run_reduction_pct",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run weighted_algo + analyze_sortedness on a batch of input files and aggregate results."
        )
    )
    parser.add_argument(
        "--inputs",
        nargs="+",
        default=["tests/*.txt"],
        help="Input file globs (default: tests/*.txt).",
    )
    parser.add_argument(
        "--weighted-binary",
        default="./weighted_algo",
        help="Path to weighted_algo binary (default: ./weighted_algo).",
    )
    parser.add_argument(
        "--analyzer",
        default="scripts/analyze_sortedness.py",
        help="Path to analyze_sortedness.py (default: scripts/analyze_sortedness.py).",
    )
    parser.add_argument(
        "--python",
        default="/bin/python3",
        help="Python executable for analyzer script (default: /bin/python3).",
    )
    parser.add_argument(
        "--output",
        default="sortedness_tests_summary.csv",
        help="Output aggregate CSV path (default: sortedness_tests_summary.csv).",
    )
    parser.add_argument(
        "--comparison-output",
        default="sortedness_tests_comparison.csv",
        help=(
            "Output CSV with ordered-vs-non_ordered deltas "
            "(default: sortedness_tests_comparison.csv)."
        ),
    )
    parser.add_argument(
        "--temp-dir",
        default=".sortedness_tmp",
        help="Temporary directory for per-file intermediate CSVs (default: .sortedness_tmp).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Optional seed passed to weighted_algo for reproducibility.",
    )
    parser.add_argument(
        "--time-limit",
        type=float,
        default=None,
        help="Optional time limit (seconds) passed to weighted_algo.",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=0,
        help="Optional cap on number of input files processed (0 means all).",
    )
    parser.add_argument(
        "--max-rows-per-mode",
        type=int,
        default=200000,
        help=(
            "Cap rows per mode passed to weighted_algo and analyze_sortedness "
            "(default: 200000, 0 means all)."
        ),
    )
    parser.add_argument(
        "--mode",
        default="all",
        choices=["all", "non_ordered", "sorted_at_end", "ordered"],
        help="Run mode passed to weighted_algo (default: all).",
    )
    parser.add_argument(
        "--part-selection",
        default="first",
        choices=["first", "max_vertices", "min_avg_weight", "min_first_edge", "min_top3_mean"],
        help="Part selection method for ordered mode (default: first).",
    )
    return parser.parse_args()


def resolve_inputs(patterns: list[str]) -> list[Path]:
    files: list[Path] = []
    seen: set[Path] = set()
    for pattern in patterns:
        for match in sorted(Path().glob(pattern)):
            if match.is_file() and match not in seen:
                seen.add(match)
                files.append(match)
    return files


def run_cmd(cmd: list[str], label: str) -> tuple[bool, str]:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode == 0:
        return True, ""

    sys.stderr.write(f"[run_sortedness_tests] command failed ({label}): {' '.join(cmd)}\n")
    if proc.stdout:
        sys.stderr.write(proc.stdout)
    if proc.stderr:
        sys.stderr.write(proc.stderr)

    combined = (proc.stderr or proc.stdout or "").strip()
    first_line = combined.splitlines()[0] if combined else "command failed"
    return False, first_line


def read_summary(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="ascii", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            return []
        return list(reader)


def csv_data_row_count(path: Path) -> int:
    if not path.is_file():
        return 0
    with path.open("r", encoding="ascii", newline="") as handle:
        reader = csv.reader(handle)
        next(reader, None)
        return sum(1 for _ in reader)


def _to_float(value: str) -> float:
    if value is None or value == "":
        return 0.0
    return float(value)


def _to_int(value: str) -> int:
    if value is None or value == "":
        return 0
    return int(value)


def build_comparison_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    grouped: dict[str, dict[str, dict[str, str]]] = {}
    for row in rows:
        input_file = row.get("input_file", "")
        mode = row.get("mode", "")
        grouped.setdefault(input_file, {})[mode] = row

    comparison_rows: list[dict[str, str]] = []
    for input_file in sorted(grouped):
        by_mode = grouped[input_file]
        non_row = by_mode.get("non_ordered")
        ord_row = by_mode.get("ordered")

        if not non_row or not ord_row:
            comparison_rows.append(
                {
                    "input_file": input_file,
                    "status": "missing_mode",
                    "error_message": "ordered or non_ordered row missing",
                    "non_ordered_count": "",
                    "ordered_count": "",
                    "delta_inversion_count": "",
                    "delta_normalized_kendall_tau": "",
                    "delta_run_count": "",
                    "delta_lis_ratio": "",
                    "delta_mean_abs_delta": "",
                    "non_ordered_mean_weight": "",
                    "ordered_mean_weight": "",
                    "delta_mean_weight": "",
                    "inversion_ord_to_non_ratio": "",
                    "run_excess_ord_to_non_ratio": "",
                    "non_ordered_inv_over_max": "",
                    "ordered_inv_over_max": "",
                    "non_ordered_run_over_max": "",
                    "ordered_run_over_max": "",
                    "inversion_reduction_pct": "",
                    "run_reduction_pct": "",
                }
            )
            continue

        non_inv = _to_int(non_row.get("inversion_count", "0"))
        ord_inv = _to_int(ord_row.get("inversion_count", "0"))
        non_runs = _to_int(non_row.get("run_count", "0"))
        ord_runs = _to_int(ord_row.get("run_count", "0"))
        non_tau = _to_float(non_row.get("normalized_kendall_tau", "0"))
        ord_tau = _to_float(ord_row.get("normalized_kendall_tau", "0"))
        non_lis = _to_float(non_row.get("lis_ratio", "0"))
        ord_lis = _to_float(ord_row.get("lis_ratio", "0"))
        non_mad = _to_float(non_row.get("mean_abs_delta", "0"))
        ord_mad = _to_float(ord_row.get("mean_abs_delta", "0"))
        non_mean_weight = _to_float(non_row.get("mean_weight", "0"))
        ord_mean_weight = _to_float(ord_row.get("mean_weight", "0"))
        non_count = _to_int(non_row.get("count", "0"))
        ord_count = _to_int(ord_row.get("count", "0"))

        inv_reduction_pct = ((non_inv - ord_inv) / non_inv * 100.0) if non_inv > 0 else 0.0

        # Run disorder is the excess above the sorted optimum (1 run).
        non_excess_runs = max(non_runs - 1, 0)
        ord_excess_runs = max(ord_runs - 1, 0)
        if non_excess_runs > 0:
            run_reduction_pct = ((non_excess_runs - ord_excess_runs) / non_excess_runs) * 100.0
        elif ord_excess_runs > 0:
            run_reduction_pct = -100.0
        else:
            run_reduction_pct = 0.0

        inv_ratio = (ord_inv / non_inv) if non_inv > 0 else (1.0 if ord_inv == 0 else 0.0)
        run_excess_ratio = (
            (ord_excess_runs / non_excess_runs)
            if non_excess_runs > 0
            else (1.0 if ord_excess_runs == 0 else 0.0)
        )

        non_max_inv = (non_count * (non_count - 1)) // 2
        ord_max_inv = (ord_count * (ord_count - 1)) // 2
        non_inv_over_max = (non_inv / non_max_inv) if non_max_inv > 0 else 0.0
        ord_inv_over_max = (ord_inv / ord_max_inv) if ord_max_inv > 0 else 0.0

        # Normalize run disorder by excess runs: (run_count - 1) / (n - 1).
        # This makes the sorted optimum equal to 0.0 (since run_count == 1).
        non_run_over_max = (
            (non_excess_runs / (non_count - 1)) if non_count > 1 else 0.0
        )
        ord_run_over_max = (
            (ord_excess_runs / (ord_count - 1)) if ord_count > 1 else 0.0
        )

        comparison_rows.append(
            {
                "input_file": input_file,
                "status": "ok",
                "error_message": "",
                "non_ordered_count": non_row.get("count", ""),
                "ordered_count": ord_row.get("count", ""),
                "delta_inversion_count": str(ord_inv - non_inv),
                "delta_normalized_kendall_tau": f"{(ord_tau - non_tau):.6f}",
                "delta_run_count": str(ord_runs - non_runs),
                "delta_lis_ratio": f"{(ord_lis - non_lis):.6f}",
                "delta_mean_abs_delta": f"{(ord_mad - non_mad):.6f}",
                "non_ordered_mean_weight": f"{non_mean_weight:.12g}",
                "ordered_mean_weight": f"{ord_mean_weight:.12g}",
                "delta_mean_weight": f"{(ord_mean_weight - non_mean_weight):.12g}",
                "inversion_ord_to_non_ratio": f"{inv_ratio:.6f}",
                "run_excess_ord_to_non_ratio": f"{run_excess_ratio:.6f}",
                "non_ordered_inv_over_max": f"{non_inv_over_max:.6f}",
                "ordered_inv_over_max": f"{ord_inv_over_max:.6f}",
                "non_ordered_run_over_max": f"{non_run_over_max:.6f}",
                "ordered_run_over_max": f"{ord_run_over_max:.6f}",
                "inversion_reduction_pct": f"{inv_reduction_pct:.6f}",
                "run_reduction_pct": f"{run_reduction_pct:.6f}",
            }
        )

    return comparison_rows


def main() -> None:
    args = parse_args()

    weighted_binary = Path(args.weighted_binary).resolve()
    analyzer = Path(args.analyzer).resolve()
    if not weighted_binary.is_file():
        sys.stderr.write(f"[run_sortedness_tests] weighted binary not found: {weighted_binary}\n")
        sys.exit(1)
    if not analyzer.is_file():
        sys.stderr.write(f"[run_sortedness_tests] analyzer script not found: {analyzer}\n")
        sys.exit(1)

    inputs = resolve_inputs(args.inputs)
    if not inputs:
        sys.stderr.write("[run_sortedness_tests] no input files matched.\n")
        sys.exit(1)

    if args.max_files > 0:
        inputs = inputs[: args.max_files]

    temp_dir = Path(args.temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, str]] = []
    for index, input_path in enumerate(inputs, start=1):
        slug = input_path.stem
        weights_csv = temp_dir / f"{slug}.weights.csv"
        summary_csv = temp_dir / f"{slug}.summary.csv"

        weighted_cmd = [str(weighted_binary), str(input_path)]
        if args.time_limit is not None:
            seed_value = args.seed if args.seed is not None else 12345
            weighted_cmd.extend([f"{args.time_limit:g}", str(weights_csv)])
            weighted_cmd.append(str(seed_value))
            weighted_cmd.append(args.mode)
        else:
            weighted_cmd.extend([args.mode, str(weights_csv)])
            seed_value = args.seed if args.seed is not None else 12345
            weighted_cmd.append(str(seed_value))

        weighted_cmd.append(str(args.max_rows_per_mode))
        
        # Add part_selection parameter if mode is ordered
        if args.mode == "ordered":
            weighted_cmd.append(args.part_selection)

        ok, err = run_cmd(weighted_cmd, f"weighted_algo:{input_path}")
        if not ok:
            rows.append(
                {
                    "input_file": str(input_path),
                    "status": "solver_error",
                    "error_message": err,
                    "mode": "",
                    "count": "",
                    "inversion_count": "",
                    "normalized_kendall_tau": "",
                    "run_count": "",
                    "lis_ratio": "",
                    "mean_abs_delta": "",
                    "mean_weight": "",
                }
            )
            sys.stderr.write(
                f"[run_sortedness_tests] processed {index}/{len(inputs)}: {input_path} (solver_error)\n"
            )
            continue

        if csv_data_row_count(weights_csv) == 0:
            rows.append(
                {
                    "input_file": str(input_path),
                    "status": "no_data",
                    "error_message": "",
                    "mode": "",
                    "count": "0",
                    "inversion_count": "",
                    "normalized_kendall_tau": "",
                    "run_count": "",
                    "lis_ratio": "",
                    "mean_abs_delta": "",
                    "mean_weight": "",
                }
            )
            sys.stderr.write(
                f"[run_sortedness_tests] processed {index}/{len(inputs)}: {input_path} (no_data)\n"
            )
            continue

        analyze_cmd = [
            args.python,
            str(analyzer),
            "--input",
            str(weights_csv),
            "--output",
            str(summary_csv),
            "--max-rows-per-mode",
            str(args.max_rows_per_mode),
        ]
        ok, err = run_cmd(analyze_cmd, f"analyze_sortedness:{input_path}")
        if not ok:
            rows.append(
                {
                    "input_file": str(input_path),
                    "status": "analyzer_error",
                    "error_message": err,
                    "mode": "",
                    "count": "",
                    "inversion_count": "",
                    "normalized_kendall_tau": "",
                    "run_count": "",
                    "lis_ratio": "",
                    "mean_abs_delta": "",
                    "mean_weight": "",
                }
            )
            sys.stderr.write(
                f"[run_sortedness_tests] processed {index}/{len(inputs)}: {input_path} (analyzer_error)\n"
            )
            continue

        per_file_rows = read_summary(summary_csv)
        for row in per_file_rows:
            rows.append(
                {
                    "input_file": str(input_path),
                    "status": "ok",
                    "error_message": "",
                    **row,
                }
            )

        sys.stderr.write(
            f"[run_sortedness_tests] processed {index}/{len(inputs)}: {input_path}\n"
        )

    with Path(args.output).open("w", encoding="ascii", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SUMMARY_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    comparison_rows = build_comparison_rows(rows)
    with Path(args.comparison_output).open("w", encoding="ascii", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COMPARISON_FIELDS)
        writer.writeheader()
        for row in comparison_rows:
            writer.writerow(row)

    sys.stderr.write(
        f"[run_sortedness_tests] wrote {len(rows)} row(s) to {args.output}.\n"
    )
    sys.stderr.write(
        "[run_sortedness_tests] wrote "
        f"{len(comparison_rows)} comparison row(s) to {args.comparison_output}.\n"
    )


if __name__ == "__main__":
    main()
