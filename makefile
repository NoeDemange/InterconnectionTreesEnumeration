# Compiler and flags
CC = gcc
CFLAGS = -O2
LDLIBS = -lm
PYTHON = /bin/python3

# Executable names
WEIGHTED_EXEC = weighted_algo

# Source files
WEIGHTED_SRC = weighted_algo.c

# Default target
all: clean $(WEIGHTED_EXEC)

# Compile weighted_algo
$(WEIGHTED_EXEC): $(WEIGHTED_SRC)
	$(CC) $(CFLAGS) -o $(WEIGHTED_EXEC) $(WEIGHTED_SRC) $(LDLIBS)

# Run weighted_algo (with input_file as argument)
run_weighted: $(WEIGHTED_EXEC)
	./$(WEIGHTED_EXEC) tests/realYARZUN03.txt

# Run weighted_algo in all mode and export tree weights to CSV
run_weighted_all: $(WEIGHTED_EXEC)
	./$(WEIGHTED_EXEC) tests_random/3Comp9Ver.txt all weights_sequences.csv

# Repeat randomized weighted runs on the proposed SYNTHETIC input (100 reps)
run_weighted_randomized: $(WEIGHTED_EXEC)
	$(PYTHON) scripts/run_weighted_randomized_average.py tests_random/SYNTHETIC.txt --reps 100 --seed 12345 --max-rows-per-mode 0 --output-summary SYNTHETIC_average_summary_100.csv --output-raw SYNTHETIC_average_runs_100.csv

# Repeat randomized weighted runs on 3Comp9Ver (100 reps)
run_weighted_randomized_3comp9: $(WEIGHTED_EXEC)
	$(PYTHON) scripts/run_weighted_randomized_average.py tests_random/3Comp9Ver.txt --reps 100 --seed 12345 --max-rows-per-mode 0 --output-summary 3Comp9Ver_average_summary_100.csv --output-raw 3Comp9Ver_average_runs_100.csv

# Analyze sortedness metrics from weighted_algo CSV output
analyze_sortedness: run_weighted_all
	$(PYTHON) scripts/analyze_sortedness.py --input weights_sequences.csv --output sortedness_summary.csv

# Display sortedness summary in terminal
show_sortedness: analyze_sortedness
	cat sortedness_summary.csv

# Run sortedness analysis on all files in tests/ (no limit on rows per mode)
analyze_sortedness_tests: $(WEIGHTED_EXEC)
	$(PYTHON) scripts/run_sortedness_tests.py --inputs tests/*.txt --weighted-binary ./$(WEIGHTED_EXEC) --analyzer scripts/analyze_sortedness.py --output sortedness_tests_summary.csv --max-rows-per-mode 0

# Run sortedness analysis on all files in tests/ (limit to 10 000 rows per mode)
analyze_sortedness_tests_10000: $(WEIGHTED_EXEC)
	$(PYTHON) scripts/run_sortedness_tests.py --inputs tests/*.txt --weighted-binary ./$(WEIGHTED_EXEC) --analyzer scripts/analyze_sortedness.py --output sortedness_tests_summary.csv --max-rows-per-mode 10000

# Display per-test sortedness summary
show_sortedness_tests: analyze_sortedness_tests
	head -n 40 sortedness_tests_summary.csv

# Display ordered vs non_ordered deltas per test file
show_sortedness_diff: analyze_sortedness_tests
	head -n 40 sortedness_tests_comparison.csv

# Test part selection methods in ordered mode on all test files
test_part_selection: $(WEIGHTED_EXEC)
	$(PYTHON) scripts/run_part_selection_tests.py --inputs tests/*.txt --weighted-binary ./$(WEIGHTED_EXEC) --analyzer scripts/analyze_sortedness.py --output part_selection_ordered_tests.csv --max-rows-per-mode 0

# Display part selection test results
show_part_selection: test_part_selection
	head -n 20 part_selection_ordered_tests.csv

# Clean up generated files
clean:
	rm -f $(WEIGHTED_EXEC)
