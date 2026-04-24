# Interconnection Trees Enumeration

## Goal

The goal of this project is to implement algorithms that **enumerate all possible interconnection trees** of a given partition. A partition comes from a graph whose free vertices of the connected components form a set. An interconnection tree is a subset of edges that connects all parts (connected components of a graph) without forming a cycle, i.e. a spanning tree over the components.

## Usage

### Build

The Makefile is now focused on `weighted_algo`.

1. To build `weighted_algo.c`:
    ```bash
    make
    # or
    make weighted_algo
    ```

2. To clean generated files:
    ```bash
    make clean
    ```

3. To build and run `weighted_algo` quickly:
    ```bash
    make run_weighted
    ```

4. `weighted_algo`: full parameter specification

    General syntax, in the actual parsing order:
    ```bash
    ./weighted_algo <input_file> [time_limit_seconds|mode] [output_csv] [random_seed] [mode] [max_rows_per_mode] [part_selection]
    ```

    Parameters:
    - `input_file` (required): partition file.
    - `[time_limit_seconds|mode]` (optional):
        - either a time limit (a float strictly greater than `0`),
        - or a mode (`all`, `non_ordered`, `sorted_at_end`, `ordered`).
    - `[output_csv]` (optional): output CSV path (default: `weights_sequences.csv`).
    - `[random_seed]` (optional): unsigned integer (`0..UINT_MAX`) used to seed random weights (default: `time(NULL)`).
    - `[mode]` (optional): mode, useful when the second argument was a `time_limit_seconds` value.
    - `[max_rows_per_mode]` (optional): integer `>= 0`.
        - `0` = no limit.
        - `> 0` = limit storage and stop enumeration early once the bound is reached.
    - `[part_selection]` (optional): component-selection method used to initialize `ordered` mode.

    Accepted modes:
    - `all`
    - `non_ordered` (aliases: `non-ordered`, `non`)
    - `sorted_at_end` (aliases: `sorted-at-end`, `sorted`)
    - `ordered`

    Accepted `part_selection` methods:
    - `min_first_edge` (default)
    - `max_vertices`
    - `min_avg_weight`
    - `min_vertices`

    Important notes:
    - `part_selection` only has an effect when the executed mode is `ordered`.
    - If an argument appears in the expected position but is invalid (seed, mode, max_rows, etc.), execution fails.
    - The program accepts at most 7 user arguments after the executable name.

    Valid examples:
    ```bash
    # Mode in second position (no time limit)
    ./weighted_algo tests_random/3Comp9Ver.txt all weights_sequences.csv

    # Time limit in second position, then mode later
    ./weighted_algo tests_random/3Comp9Ver.txt 120 weights.csv 12345 non_ordered

    # ordered mode with an explicit selection method
    ./weighted_algo tests_random/3Comp9Ver.txt ordered weights.csv 12345 ordered 0 max_vertices

    # Run with defaults (mode all, default CSV, seed based on the clock)
    ./weighted_algo tests_random/3Comp9Ver.txt
    ```

    The produced CSV contains the columns: `mode`, `rank`, `total_weight`.

5. To run the full “weighted + sortedness analysis” pipeline:
    ```bash
    make show_sortedness
    ```

6. To run sortedness analysis on **all files** in the `tests/` directory:
    ```bash
    make show_sortedness_tests
    ```
    This target generates `sortedness_tests_summary.csv` with one row per (`input_file`, `mode`) pair.

    To display the direct `ordered` vs `non_ordered` difference per file:
    ```bash
    make show_sortedness_diff
    ```
    This target reads `sortedness_tests_comparison.csv`.

7. To repeat the same file with **fresh random weights** on each run, use `scripts/run_weighted_randomized_average.py`.

    Important: in each repetition, the script runs `weighted_algo` in `all` mode, so the weight matrix is the same across `non_ordered`, `sorted_at_end`, and `ordered` for that repetition (fair comparison).

    Direct example (the originally proposed case, 100 repetitions):
    ```bash
    python3 scripts/run_weighted_randomized_average.py tests_random/SYNTHETIC.txt --reps 100 --seed 12345 --max-rows-per-mode 0 --output-summary SYNTHETIC_average_summary_100.csv --output-raw SYNTHETIC_average_runs_100.csv
    ```

    Via Makefile:
    ```bash
    make run_weighted_randomized
    make run_weighted_randomized_3comp9
    ```

    Generated files:
    - `*_average_runs_*.csv`: one line per repetition and per mode.
    - `*_average_summary_*.csv`: mean, standard deviation, minimum, and maximum of the metrics per mode.

### Sortedness analysis (`scripts/analyze_sortedness.py`)

The script reads the `weighted_algo` CSV (`mode,rank,total_weight`) and analyses each mode on its **raw sequence**.
The reference used for the order metrics is the ideal increasing order of that same sequence (stable sort by weight).

Command:
```bash
/bin/python3 scripts/analyze_sortedness.py --input weights_sequences.csv --output sortedness_summary.csv
```

Main output columns:
- `inversion_count`: number of inverted pairs (adjacent-swap distance).
- `normalized_kendall_tau`: `inversion_count` normalized to `[0,1]`.
- `run_count`: number of monotone runs (smaller = better sorted).
- `lis_ratio`: LIS length / n (larger = better sorted).
- `mean_abs_delta`: mean absolute rank displacement from the ideal increasing order.
- `mean_weight`: mean weight of the raw sequence.

### Batch on `tests/` (`scripts/run_sortedness_tests.py`)

The script `scripts/run_sortedness_tests.py` automates the following loop for each test file:
1. run `weighted_algo` in `all` mode;
2. run `scripts/analyze_sortedness.py` on the produced CSV;
3. aggregate the result into a final CSV.

Direct example:
```bash
/bin/python3 scripts/run_sortedness_tests.py --inputs tests/*.txt --weighted-binary ./weighted_algo --output sortedness_tests_summary.csv
```

Useful options:
- `--seed <int>`: fixed seed for reproducible comparisons.
- `--time-limit <sec>`: time limit forwarded to `weighted_algo`.
- `--max-files <n>`: limit the number of processed files.

### Component-selection comparison (`scripts/run_part_selection_tests.py`)

The script `scripts/run_part_selection_tests.py` tests and compares the **four component-selection methods** available in `ordered` mode of `weighted_algo`. Each method is a different starting point for the ordered enumeration, which can affect the sortedness of the enumeration sequence.

#### Tested selection methods

1. **`max_vertices`**: selects the component with the **most vertices** (tie-break: `min_first_edge`).
2. **`min_avg_weight`**: selects the component with the **minimum average edge weight** (total_weight / number_of_edges).
3. **`min_first_edge`**: selects the component whose **lightest edge is minimal** (lexicographic tie-break).
4. **`min_vertices`**: selects the component with the **fewest vertices** (tie-break: `min_first_edge`).

#### Output format

The script generates a CSV with **one row per method** (for each input file), allowing direct comparison of sortedness metrics:

| Column | Description |
|---------|-------------|
| `input_file` | Input file name |
| `part_selection` | Tested method (`max_vertices`, `min_avg_weight`, etc.) |
| `status` | Result: `success`, `error`, `no_data`, or `analysis_error` |
| `part_id` | Selected component (0-based index) |
| `count` | Number of interconnection trees enumerated |
| `inversion_count` | Number of inverted pairs in the sequence |
| `run_count` | Number of monotone runs (smaller = better sorted) |
| `mean_weight` | Mean weight of the enumerated trees |
| `error_message` | Error details if `status != success` |

#### Usage

Via Makefile (compiles `weighted_algo` if needed):
```bash
make test_part_selection   # run the script on all tests/*.txt files
make show_part_selection   # display the first 20 lines of the result CSV
```

Direct script execution:
```bash
python3 scripts/run_part_selection_tests.py --inputs tests/*.txt --output part_selection_results.csv
```

Available options:
- `--inputs PATTERN`: glob pattern for input files (e.g. `tests/*.txt`).
- `--output FILE`: output CSV file (default: `part_selection_results.csv`).
- `--weighted-binary BINARY`: path to the `weighted_algo` executable (default: `./weighted_algo`).
- `--seed SEED`: fixed random seed for weight generation (the same seed is used for all files).

#### Example result

```csv
input_file,part_selection,status,part_id,count,inversion_count,run_count,mean_weight
realBAHSUY.txt,max_vertices,success,0,6,0,1,7.793
realBAHSUY.txt,min_avg_weight,success,0,6,0,1,7.793
realBAHSUY.txt,min_first_edge,success,0,6,0,1,7.793
realBAHSUY.txt,min_vertices,success,0,6,0,1,7.793
realYARZUN03.txt,max_vertices,success,1,8,3,2,4.256
realYARZUN03.txt,min_avg_weight,success,2,8,2,2,4.256
realYARZUN03.txt,min_first_edge,success,1,8,3,2,4.256
realYARZUN03.txt,min_vertices,success,1,8,3,2,4.256
```

#### Interpretation

- Compare `inversion_count` and `run_count` **per file** to see which method yields better sortedness.
- Identical values (e.g. the first example above) mean that all four methods selected the same component.
- Different values (e.g. `realYARZUN03.txt`) show the effect of the choice: `min_avg_weight` produces a less inverted sequence here (`inversion_count=2` vs `3`).

#### Notes

- The script runs only the **`ordered`** mode of `weighted_algo`, skipping `non_ordered` and `sorted_at_end` to save time.
- The metrics `count`, `inversion_count`, `run_count`, and `mean_weight` are computed via `scripts/analyze_sortedness.py` directly on the raw `ordered` sequence.
- Weights are generated randomly. Use `--seed` to reproduce results.
- Each input file produces **four rows** (one per method).
- `--max-rows-per-mode <n>`: per-mode row limit for the analysis (default `200000`, `0` = all rows).
- `--mode <all|non_ordered|sorted_at_end|ordered>`: mode passed to `weighted_algo` (default `all`).
- `--part-selection <max_vertices|min_avg_weight|min_first_edge|min_vertices>`: main component-selection method when `--mode ordered`.

Practical note: some instances can generate tens of millions of lines. The `--max-rows-per-mode` limit keeps batch analysis times reasonable.

Output file:
- `sortedness_tests_summary.csv`
- Columns: `input_file`, `status`, `error_message`, `mode`, and all sortedness metrics.
- `status=ok`: the analysis was computed.
- `status=no_data`: the instance produced no weighted solutions.
- `status=solver_error`: `weighted_algo` failed on the file.
- `status=analyzer_error`: the analysis failed on the file.

Direct `ordered` vs `non_ordered` comparison:
- `sortedness_tests_comparison.csv`
- Difference columns (`delta_*`) are computed as `ordered - non_ordered`.
- Weight average columns:
    - `non_ordered_mean_weight`, `ordered_mean_weight`.
    - `delta_mean_weight = ordered_mean_weight - non_ordered_mean_weight`.
- Ordered/non-ordered ratios:
    - `inversion_ord_to_non_ratio = inversion_ordered / inversion_non_ordered`.
    - `run_excess_ord_to_non_ratio = (run_ordered - 1) / (run_non_ordered - 1)`.
- Ratios normalized by the theoretical maximum:
    - `non_ordered_inv_over_max`, `ordered_inv_over_max` with `max_inv = n*(n-1)/2` and `n = count`.
    - `non_ordered_run_over_max`, `ordered_run_over_max` normalized by excess runs: `(run_count - 1) / (n - 1)` with `n = count` (so `0` for a perfectly sorted sequence).
- Quick interpretation:
    - `delta_inversion_count < 0`: ordered has fewer inversions (better).
    - `delta_run_count < 0`: ordered has fewer runs (better).
    - `delta_lis_ratio > 0`: ordered has a larger LIS (better).
    - `inversion_ord_to_non_ratio < 1`: ordered has fewer inversions.
    - `run_excess_ord_to_non_ratio < 1`: ordered has fewer excess runs.
    - `inversion_reduction_pct` (in %): relative gain of ordered over inversion count.
    - `run_reduction_pct` (in %): relative gain of ordered over excess runs (`run_count - 1`, because the sorted optimum is 1 run).


### Input file

The input file must be structured as follows:

- The first line contains two integers:
  - the total number of vertices in the partition;
  - the number of parts in the partition.

- The following lines indicate, for each vertex, which part it belongs to. The line number represents the vertex and the integer on the line represents the part.

### Example input file:
```
5 2
0
0
0
1
1
```

In this example:
- The graph has 5 vertices.
- There are 2 parts, and each vertex is assigned to a specific part.
