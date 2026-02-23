#!/usr/bin/env bash
set -x
set -u
set -o pipefail

# run read/write linters and apply safe fixes:
ruff format
ruff check --fix

# unittest:
pytest --cov --cov-report=term-missing --cov-report=xml:coverage.xml

# run read-only linters:
pyright --warnings
