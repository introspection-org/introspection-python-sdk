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

# Patterns that indicate a background span/trace exporter failure.
# These don't crash the example process but still mean the example
# didn't do what it claims (export to the backend), so we fail CI.
EXPORT_FAILURE_PATTERNS='Failed to export span batch|OTLPExporterError|span export failed|Failed to send multipart request\. Received status|Invalid credentials\. Confirm that you.ve configured the correct host|One exporter failed to send spans|LangSmithError|Failed to (send compressed )?multipart ingest'

for example in $(find introspection_examples -name "*.py" -not -name "__init__.py" -not -path "*__pycache__*" | sort); do
  echo "--- $example ---"
  count=$((count + 1))
  output=$(uv run python "$example" 2>&1)
  status=$?
  echo "$output"
  if [ $status -ne 0 ]; then
    echo "FAILED: $example"
    failed=$((failed + 1))
  elif echo "$output" | grep -qE "$EXPORT_FAILURE_PATTERNS"; then
    echo "FAILED (exporter error): $example"
    failed=$((failed + 1))
  fi
done

echo ""
echo "========================================"
echo "Ran $count examples, $failed failed"
exit $((failed > 0))
