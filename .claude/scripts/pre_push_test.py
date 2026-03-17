"""
PreToolUse hook — runs before every Bash tool call.
If the command is a git push, runs pytest first and blocks the push if any test fails.
"""
import sys
import json
import subprocess
import os

data = json.load(sys.stdin)
cmd = data.get("command", "")

if "git push" not in cmd:
    sys.exit(0)

# Resolve project root (two levels up from .claude/scripts/)
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

print("=" * 60)
print("🧪  Running tests before push...")
print("=" * 60)

result = subprocess.run(
    [sys.executable, "-m", "pytest", "tests/", "-v", "--tb=short"],
    cwd=project_root,
)

if result.returncode != 0:
    print("\n" + "=" * 60)
    print("❌  Tests FAILED — push blocked.")
    print("    Fix the failing tests, then push again.")
    print("=" * 60)
    sys.exit(1)

print("\n" + "=" * 60)
print("✅  All tests passed — proceeding with push.")
print("=" * 60)
