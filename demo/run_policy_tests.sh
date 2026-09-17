#!/usr/bin/env bash
# Run the Guardrail Engine's policy tests with OPA in Docker, so no local OPA install is needed.
# OPA ships as a Go binary and isn't installable with uv.
#   ./run_policy_tests.sh        # summary
#   ./run_policy_tests.sh -v     # one line per test
set -euo pipefail
OPA_IMAGE="${OPA_IMAGE:-openpolicyagent/opa:1.20.2}"
POLICIES="$(cd "$(dirname "$0")" && pwd)/governed_automation/policies"
exec docker run --rm -v "$POLICIES:/policies" "$OPA_IMAGE" test /policies "$@"
