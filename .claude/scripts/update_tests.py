"""
PostToolUse hook — runs after Edit/Write tool calls.
If a non-test .py file was changed, reminds Claude to update tests.
"""
import sys
import json
import os

data = json.load(sys.stdin)
file_path = data.get("file_path", "")
basename = os.path.basename(file_path)

if file_path.endswith(".py") and not basename.startswith("test_") and basename != "conftest.py":
    print(
        f"\n⚠️  [{basename}] was modified.\n"
        "Run /qa to update tests/test_main.py so coverage stays current.\n"
    )
