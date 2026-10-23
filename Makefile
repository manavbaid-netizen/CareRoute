.PHONY: help test run demo lint check generate-seeds clean

PYTHON ?= python3

help:
	@echo "CareRoute Developer Commands:"
	@echo "  make test            Run pytest test suite"
	@echo "  make run             Run multi-agent system"
	@echo "  make demo            Run interactive local demo walkthrough"
	@echo "  make lint            Run ruff linter"
	@echo "  make check           Run ruff and pytest"
	@echo "  make generate-seeds  Generate fresh random seed phrases for .env"
	@echo "  make clean           Remove cached files and databases"

test:
	pytest -v

run:
	$(PYTHON) run_all.py

demo:
	$(PYTHON) main.py --demo

lint:
	ruff check .

check: lint test

generate-seeds:
	$(PYTHON) scripts/generate_seeds.py

clean:
	rm -rf __pycache__ */__pycache__ */*/__pycache__ .pytest_cache .ruff_cache data/*.db data/dossiers/* data/bookings/*
