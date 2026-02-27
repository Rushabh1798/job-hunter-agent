#!/bin/bash
# Autonomous Claude Code loop — runs until GOAL.md criteria are met.
#
# Usage:
#   chmod +x scripts/run_autonomous.sh
#   ./scripts/run_autonomous.sh
#
# This script:
# 1. Reads GOAL.md and docs/ANALYSIS.md for context
# 2. Runs Claude Code with a targeted fix prompt
# 3. Runs the pipeline
# 4. Verifies output against goals
# 5. Loops until all goals pass or max iterations reached

set -euo pipefail

MAX_ITERATIONS=5
ITERATION=0
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

LOG_DIR="$PROJECT_DIR/output/autonomous_logs"
mkdir -p "$LOG_DIR"

echo "=========================================="
echo "Autonomous Job Hunter Pipeline Fix Loop"
echo "=========================================="
echo "Project: $PROJECT_DIR"
echo "Max iterations: $MAX_ITERATIONS"
echo ""

while [ $ITERATION -lt $MAX_ITERATIONS ]; do
    ITERATION=$((ITERATION + 1))
    TIMESTAMP=$(date +%Y%m%d_%H%M%S)
    ITER_LOG="$LOG_DIR/iteration_${ITERATION}_${TIMESTAMP}.log"

    echo ""
    echo "--- Iteration $ITERATION of $MAX_ITERATIONS ($TIMESTAMP) ---"

    # Step 1: Run Claude Code to fix issues
    echo "[Step 1] Running Claude Code to fix pipeline issues..."

    CLAUDE_PROMPT="You are working on the job-hunter-agent project. Your goal is defined in GOAL.md.
Read GOAL.md, docs/ANALYSIS.md, and the latest pipeline output log (output/live_run.log) to understand the current state.

IMPORTANT RULES:
- Do NOT ask any questions. Make the best decision and proceed.
- Do NOT create new files unless absolutely necessary.
- Run 'uv run pytest -m unit -q' after each change to verify tests pass.
- Focus on the highest-priority unfixed issue from docs/ANALYSIS.md.
- After fixing code, run the pipeline: 'uv run python run_live_pipeline.py'
- After the pipeline completes, run 'uv run python scripts/verify_goal.py' to check goals.
- Update docs/ANALYSIS.md with your findings.
- Keep changes minimal and focused.

Current iteration: $ITERATION of $MAX_ITERATIONS.
The pipeline was last run and the results are in output/live_run.log.

Fix the highest-priority issue, run the pipeline, and verify goals."

    # Run Claude Code non-interactively
    claude --print --dangerously-skip-permissions \
        -p "$CLAUDE_PROMPT" \
        2>&1 | tee "$ITER_LOG" || true

    # Step 2: Verify goals
    echo ""
    echo "[Step 2] Verifying goals..."
    if uv run python scripts/verify_goal.py 2>&1; then
        echo ""
        echo "=========================================="
        echo "ALL GOALS MET after $ITERATION iteration(s)!"
        echo "=========================================="
        exit 0
    fi

    echo ""
    echo "Goals not yet met. Continuing to next iteration..."
done

echo ""
echo "=========================================="
echo "MAX ITERATIONS ($MAX_ITERATIONS) REACHED"
echo "Goals not fully met. Review output in $LOG_DIR"
echo "=========================================="
exit 1
