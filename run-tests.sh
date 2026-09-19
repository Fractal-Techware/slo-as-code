#!/usr/bin/env bash
# FTW SLO-as-Code (free edition) - validate and test everything in this folder.
#
#   ./run-tests.sh
#
# 1. unit tests (pytest if installed, otherwise unittest): parser, validation, math,
#    templates, golden files
# 2. ftw-slo validate on the examples
# 3. promtool check rules on every generated rule file
# 4. promtool test rules: burn-rate timing tests for every SLI template
#
# Uses promtool from your PATH when available, otherwise the pinned Docker image
# below. Set FTW_USE_DOCKER=1 to force Docker.
set -euo pipefail
cd "$(dirname "$0")"

PROMETHEUS_IMAGE="${PROMETHEUS_IMAGE:-prom/prometheus:v3.14.0}"
PYTHON="${PYTHON:-python3}"

# promtool from PATH when available, otherwise the pinned Docker image.
run_promtool() {
  if [ -z "${FTW_USE_DOCKER:-}" ] && command -v promtool >/dev/null 2>&1; then
    promtool "$@"
  else
    docker run --rm -v "$PWD:/kit:ro" -w /kit --entrypoint promtool "$PROMETHEUS_IMAGE" "$@"
  fi
}

echo "==> unit tests"
if "$PYTHON" -c "import pytest" >/dev/null 2>&1; then
  "$PYTHON" -m pytest -q -p no:cacheprovider tests/unit
else
  "$PYTHON" -m unittest discover -s tests/unit
fi

echo "==> ftw-slo validate examples/"
"$PYTHON" ftw-slo validate examples >/dev/null
echo "  SUCCESS"

shopt -s nullglob
rule_files=(generated/rules/*.yml tests/promtool/rules/*.yml)
test_files=(tests/promtool/*.test.yml)

echo "==> promtool check rules (${#rule_files[@]} files)"
run_promtool check rules "${rule_files[@]}" >/dev/null
echo "  SUCCESS"

echo "==> promtool test rules (${#test_files[@]} files, 18 scenarios, ~30s)"
run_promtool test rules "${test_files[@]}"

echo "All checks passed."
