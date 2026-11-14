"""Hermes cron entrypoint: standard library only, no model usage.

Install under ~/.hermes/scripts and set HERMES_FEEDBACK_CHECKOUT to an
approved local Hermes Unlimited checkout. The sender itself refuses absent
local opt-in and unavailable public GitHub receiver.
"""
import os
from pathlib import Path
import subprocess
import sys


def main():
    checkout = Path(os.getenv("HERMES_FEEDBACK_CHECKOUT", str(Path.home() / "hermes-unlimited-community")))
    entry = checkout / "feedback_task_model" / "feedback.py"
    if not entry.is_file():
        print("NOT_SENT_NO_INSTALLED_FEEDBACK_MODULE")
        return 0
    p = subprocess.run([sys.executable, str(entry), "publish"],
                       capture_output=True, text=True, timeout=60, check=False)
    print((p.stdout or "").strip() if p.returncode == 0 else "NOT_SENT_SENDER_ERROR")
    return p.returncode


if __name__ == "__main__":
    raise SystemExit(main())
