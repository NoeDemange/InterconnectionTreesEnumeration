#!/usr/bin/env python3
"""
Run weighted_algo in ORDERED mode ONLY with different part selection methods.
For each method, extract selected part ID, count, inversion_count, run_count, and mean_weight.
Metrics are computed with analyze_sortedness directly on the ordered raw sequence.
Output: One row per method per file (for easy comparison).
"""

import argparse
import csv
import subprocess
import sys
from pathlib import Path


PART_SELECTION_METHODS = [
    "max_vertices",
    "min_avg_weight", 
    "min_first_edge",
    "min_vertices",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Test part selection methods in ordered mode on test files"
    )
    parser.add_argument(
        "--inputs",
        nargs="+",
        default=["tests/*.txt"],
        help="Input file globs (default: tests/*.txt)",
    )
    parser.add_argument(
        "--weighted-binary",
        default="./weighted_algo",
        help="Path to weighted_algo binary (default: ./weighted_algo)",
    )
    parser.add_argument(
        "--analyzer",
        default="scripts/analyze_sortedness.py",
        help="Path to analyze_sortedness.py (default: scripts/analyze_sortedness.py)",
    )
    parser.add_argument(
        "--python",
        default="/bin/python3",
        help="Python executable for analyzer script (default: /bin/python3)",
    )
    parser.add_argument(
        "--output",
        default="part_selection_ordered_tests.csv",
        help="Output CSV path (default: part_selection_ordered_tests.csv)",
    )
    parser.add_argument(
        "--temp-dir",
        default=".part_selection_tmp",
        help="Temporary directory for intermediate files (default: .part_selection_tmp)",
    )
    parser.add_argument(
        "--max-rows-per-mode",
        type=int,
        default=0,
        help="Max rows per mode, 0 means unlimited (default: 0)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=12345,
        help="Random seed (default: 12345)",
    )
    return parser.parse_args()


def resolve_inputs(patterns: list[str]) -> list[Path]:
    """Resolve glob patterns to list of input files."""
    files: list[Path] = []
    seen: set[Path] = set()
    for pattern in patterns:
        for match in sorted(Path().glob(pattern)):
            if match.is_file() and match not in seen:
                seen.add(match)
                files.append(match)
    return files


def run_cmd(cmd: list[str], label: str) -> tuple[bool, str, str]:
    """Run command and return success, stderr, stdout."""
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode == 0:
        return True, proc.stderr, proc.stdout
    
    sys.stderr.write(f"[run_part_selection_tests] command failed ({label}): {' '.join(cmd)}\n")
    if proc.stdout:
        sys.stderr.write(proc.stdout)
    if proc.stderr:
        sys.stderr.write(proc.stderr)
    
    error_msg = (proc.stderr or proc.stdout or "").strip()
    first_line = error_msg.splitlines()[0] if error_msg else "command failed"
    return False, proc.stderr, first_line


def extract_selected_part_id(stderr: str) -> int:
    """Extract SELECTED_PART_ID from stderr output."""
    for line in stderr.splitlines():
        if line.startswith("SELECTED_PART_ID="):
            try:
                return int(line.split("=")[1])
            except (IndexError, ValueError):
                pass
    return -1


def read_summary_metrics(path: Path) -> tuple[int, int, int, float]:
    """Read ordered mode metrics from analyze_sortedness summary CSV."""
    if not path.is_file():
        return 0, 0, 0, 0.0

    with path.open("r", encoding="ascii", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            return 0, 0, 0, 0.0

        for row in reader:
            if row.get("mode") != "ordered":
                continue
            try:
                count = int(row.get("count", "0"))
                inversion_count = int(row.get("inversion_count", "0"))
                run_count = int(row.get("run_count", "0"))
                mean_weight = float(row.get("mean_weight", "0"))
                return count, inversion_count, run_count, mean_weight
            except (ValueError, KeyError):
                return 0, 0, 0, 0.0

    return 0, 0, 0, 0.0


def read_partition_sizes(input_path: Path) -> tuple[int, int] | None:
    """Read (vertices, components) from the first line of an input file."""
    try:
        with input_path.open("r", encoding="ascii") as handle:
            first_line = handle.readline().strip()
    except OSError:
        return None

    if not first_line:
        return None

    parts = first_line.split()
    if len(parts) < 2:
        return None

    try:
        vertices = int(parts[0])
        components = int(parts[1])
    except ValueError:
        return None

    return vertices, components


def test_input_file(input_path: Path, temp_dir: Path, weighted_binary: str,
                    analyzer: str, python: str, seed: int, max_rows: int) -> list[dict]:
    """
    Test all part selection methods on a single input file in ORDERED mode only (FAST).
    Returns list of dicts, one per method.
    """
    slug = input_path.stem
    results = []

    sizes = read_partition_sizes(input_path)
    invalid_size_error = ""
    if sizes is None:
        invalid_size_error = f"Invalid header in {input_path}: expected '<vertices> <components>'"
    else:
        vertices, components = sizes
        if vertices <= 0 or components <= 0:
            invalid_size_error = (
                f"Invalid sizes in {input_path}: vertices={vertices} components={components}"
            )

    for method in PART_SELECTION_METHODS:
        weights_csv = temp_dir / f"{slug}_{method}.weights.csv"
        summary_csv = temp_dir / f"{slug}_{method}.summary.csv"
        result = {
            "input_file": input_path.name,
            "part_selection": method,
            "status": "success",
            "error_message": "",
            "part_id": "",
            "count": "",
            "inversion_count": "",
            "run_count": "",
            "mean_weight": "",
        }

        if invalid_size_error:
            result["status"] = "error"
            result["error_message"] = invalid_size_error
            results.append(result)
            continue
        
        # Run weighted_algo in ORDERED mode ONLY (much faster!)
        cmd = [
            weighted_binary,
            str(input_path),
            "ordered",
            str(weights_csv),
            str(seed),
            str(max_rows),
            method,
        ]
        
        ok, stderr, err_msg = run_cmd(cmd, f"weighted_algo:{method}")
        if not ok:
            result["status"] = "error"
            result["error_message"] = err_msg
            results.append(result)
            continue
        
        # Extract selected part ID from stderr
        part_id = extract_selected_part_id(stderr)
        result["part_id"] = str(part_id) if part_id >= 0 else ""
        
        # Check if weights CSV was generated
        if weights_csv.stat().st_size == 0:
            result["status"] = "no_data"
            results.append(result)
            continue

        analyze_cmd = [
            python,
            analyzer,
            "--input", str(weights_csv),
            "--output", str(summary_csv),
            "--max-rows-per-mode", str(max_rows),
        ]
        ok, _stderr, err_msg = run_cmd(analyze_cmd, f"analyze_sortedness:{method}")
        if not ok:
            result["status"] = "analysis_error"
            result["error_message"] = err_msg
            results.append(result)
            continue

        count, inversion_count, run_count, mean_weight = read_summary_metrics(summary_csv)

        if count == 0:
            result["status"] = "no_data"
            results.append(result)
            continue
        
        result["status"] = "success"
        result["count"] = str(count)
        result["inversion_count"] = str(inversion_count)
        result["run_count"] = str(run_count)
        result["mean_weight"] = f"{mean_weight:.12g}"
        
        results.append(result)
    
    return results


def main() -> None:
    args = parse_args()
    
    weighted_binary = Path(args.weighted_binary).resolve()
    if not weighted_binary.is_file():
        sys.stderr.write(f"[run_part_selection_tests] weighted binary not found: {weighted_binary}\n")
        sys.exit(1)
    
    inputs = resolve_inputs(args.inputs)
    if not inputs:
        sys.stderr.write("[run_part_selection_tests] no input files matched.\n")
        sys.exit(1)
    
    temp_dir = Path(args.temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)
    
    # Process all input files
    all_results: list[dict] = []
    for index, input_path in enumerate(inputs, start=1):
        file_results = test_input_file(
            input_path,
            temp_dir,
            str(weighted_binary),
            args.analyzer,
            args.python,
            args.seed,
            args.max_rows_per_mode,
        )
        all_results.extend(file_results)
        
        sys.stderr.write(f"[run_part_selection_tests] processed {index}/{len(inputs)}: {input_path.name}\n")
    
    # Write output CSV (one row per method, not per file)
    fieldnames = [
        "input_file",
        "part_selection",
        "status",
        "part_id",
        "count",
        "inversion_count",
        "run_count",
        "mean_weight",
        "error_message",
    ]
    
    with open(args.output, 'w', newline='') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames, restval='')
        writer.writeheader()
        for result in all_results:
            writer.writerow(result)
    
    sys.stderr.write(f"\n[run_part_selection_tests] Results written to {args.output}\n")
    
    # Summary
    successful = sum(1 for r in all_results if r.get("status") == "success")
    error = sum(1 for r in all_results if r.get("status") != "success")
    
    sys.stderr.write(f"\nSummary:\n")
    sys.stderr.write(f"  Successful: {successful}\n")
    sys.stderr.write(f"  Failed: {error}\n")
    
    # Group by file and show comparison
    if successful > 0:
        sys.stderr.write(f"\nComparison by file:\n")
        by_file = {}
        for result in all_results:
            fname = result['input_file']
            if fname not in by_file:
                by_file[fname] = []
            by_file[fname].append(result)
        
        for fname in sorted(by_file.keys()):
            file_results = by_file[fname]
            successful_results = [r for r in file_results if r['status'] == 'success']
            
            if successful_results:
                parts = [r.get('part_id', '') for r in successful_results]
                unique_parts = set(parts)
                
                if len(unique_parts) == 1:
                    sys.stderr.write(f"  {fname}: All methods → part {parts[0]}\n")
                else:
                    parts_by_method = {r['part_selection']: r.get('part_id', '') 
                                      for r in successful_results}
                    sys.stderr.write(f"  {fname}: {parts_by_method}\n")


if __name__ == '__main__':
    main()
