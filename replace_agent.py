"""
Downloads the clean agent.py directly from GitHub and replaces the local copy.
Usage: python replace_agent.py
"""
import urllib.request, shutil, os

url = "https://raw.githubusercontent.com/dfletcher-blip/TYR-Sport/claude/fix-crm-approval-workflows-bqAoD/agent.py"
dest = os.path.join(os.path.dirname(__file__), "agent.py")

print("Downloading clean agent.py from GitHub...")
try:
    with urllib.request.urlopen(url) as response:
        content = response.read().decode("utf-8")
    with open(dest, "w", encoding="utf-8") as f:
        f.write(content)
    print("Done. Run python run.py to start the agent.")
except Exception as e:
    print(f"Download failed: {e}")
    print("Ask your support contact for the clean agent.py file directly.")
