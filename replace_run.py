"""
Downloads the clean run.py directly from GitHub and replaces the local copy.
Usage: python replace_run.py
"""
import urllib.request, os

url = "https://raw.githubusercontent.com/dfletcher-blip/TYR-Sport/claude/fix-crm-approval-workflows-bqAoD/run.py"
dest = os.path.join(os.path.dirname(__file__), "run.py")

print("Downloading clean run.py from GitHub...")
try:
    with urllib.request.urlopen(url) as response:
        content = response.read().decode("utf-8")
    with open(dest, "w", encoding="utf-8") as f:
        f.write(content)
    print("Done. Run python run.py to start the agent.")
except Exception as e:
    print(f"Download failed: {e}")
