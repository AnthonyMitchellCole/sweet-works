# fac-py developer tasks. Works on POSIX + PowerShell via `make` (GNU).

PY ?= python

.PHONY: help install run test bench perf lint format

help:
	@echo "Targets:"
	@echo "  install   Install runtime + dev dependencies."
	@echo "  run       Run the game."
	@echo "  test      Run the functional test suite."
	@echo "  bench     Run the headless 1M-item benchmark (gated)."
	@echo "  perf      Run pytest-benchmark perf gates."
	@echo "  lint      Run ruff."
	@echo "  format    Autoformat with ruff."

install:
	$(PY) -m pip install -r requirements.txt

run:
	$(PY) main.py

test:
	$(PY) -m pytest -q -m "not bench"

bench:
	$(PY) -m bench

perf:
	$(PY) -m pytest -q tests/benchmarks -m bench --benchmark-only

lint:
	$(PY) -m ruff check src bench tests

format:
	$(PY) -m ruff format src bench tests
