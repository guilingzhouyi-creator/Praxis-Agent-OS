"""Pre-commit hook 鈥?enforce minimum 1000-line net changes per commit.

Usage:
  git commit -m "msg"                    # blocked if < 1000 lines
  SKIP_SIZE_CHECK=1 git commit -m "msg"  # bypass (emergency)
  git commit -m "msg" --no-verify        # bypass (git native)
"""
import os, subprocess, sys

THRESHOLD = 1000

if os.environ.get("SKIP_SIZE_CHECK"):
    sys.exit(0)

result = subprocess.run(
    ["git", "diff", "--cached", "--stat"],
    capture_output=True, text=True, timeout=10,
)

stats = result.stdout.strip()
if not stats:
    print("PRE-COMMIT: no staged changes 鈥?nothing to commit.")
    sys.exit(1)

# Parse last line of git diff --stat: " N files changed, M insertions(+), D deletions(-)"
lines = stats.split("\n")
last = lines[-1] if lines else ""
if "file changed" not in last and "files changed" not in last:
    print("PRE-COMMIT: cannot parse diff stat.")
    sys.exit(0)

total = 0
for part in last.split(","):
    part = part.strip()
    if "insertion" in part or "change" in part:
        try:
            total += int(part.split()[0])
        except (ValueError, IndexError):
            pass
    if "deletion" in part or "change" in part:
        try:
            total += int(part.split()[0])
        except (ValueError, IndexError):
            pass

if total < THRESHOLD:
    print(f"\n  鉀?PRE-COMMIT BLOCKED: net change ({total} lines) < threshold ({THRESHOLD} lines)")
    print(f"  鈹溾攢鈹€ Break into smaller commits of 鈮THRESHOLD} lines each")
    print(f"  鈹溾攢鈹€ Or use: SKIP_SIZE_CHECK=1 git commit ...")
    print(f"  鈹斺攢鈹€ Or use: git commit --no-verify ...\n")
    sys.exit(1)

sys.exit(0)
