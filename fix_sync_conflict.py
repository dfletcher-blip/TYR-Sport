"""
Run this once to resolve the git conflict in tools/sync.py.
Usage: python fix_sync_conflict.py
"""
import re, os

path = os.path.join(os.path.dirname(__file__), "tools", "sync.py")

with open(path, "r", encoding="utf-8") as f:
    content = f.read()

if "<<<<<<<" not in content:
    print("No conflict markers found in tools/sync.py — nothing to fix.")
else:
    # Keep HEAD version of every conflict block
    fixed = re.sub(
        r"<<<<<<< [^\n]*\n(.*?)=======[^\n]*\n.*?>>>>>>> [^\n]*\n",
        r"\1",
        content,
        flags=re.DOTALL,
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write(fixed)
    print("Fixed! tools/sync.py conflict markers removed.")
    print("You can now run: python run.py")
