#!/usr/bin/env bash
set -uo pipefail

# Load .env from this directory or parent
if [ -f ".env" ]; then
  set -a; source ".env"; set +a
elif [ -f "../.env" ]; then
  set -a; source "../.env"; set +a
fi

uv sync --all-extras

failed=0
count=0

for example in $(find introspection_examples -name "*.py" -not -name "__init__.py" -not -path "*__pycache__*" | sort); do
  echo "--- $example ---"
  count=$((count + 1))
  if ! uv run python "$example"; then
    echo "FAILED: $example"
    failed=$((failed + 1))
  fi
done

echo ""
echo "========================================"
echo "Ran $count examples, $failed failed"
exit $((failed > 0))
