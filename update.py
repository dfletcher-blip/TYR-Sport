"""
Downloads the latest versions of all agent files from GitHub.
Usage: python update.py
"""
import urllib.request, os

BRANCH = "claude/fix-crm-approval-workflows-bqAoD"
BASE = f"https://raw.githubusercontent.com/dfletcher-blip/TYR-Sport/{BRANCH}"

FILES = [
    "agent.py",
    "run.py",
    "tools/workflows.py",
    "tools/views_dashboards.py",
    "tools/special_terms.py",
    "tools/security_roles.py",
    "tools/contacts.py",
    "tools/leads.py",
    "tools/accounts.py",
    "tools/opportunities.py",
    "tools/bulk_updates.py",
    "tools/teams.py",
    "tools/reports.py",
    "tools/email.py",
    "tools/form_customization.py",
    "tools/memory.py",
    "tools/sync.py",
]

root = os.path.dirname(__file__)
ok, failed = [], []

for rel_path in FILES:
    url = f"{BASE}/{rel_path}"
    dest = os.path.join(root, rel_path.replace("/", os.sep))
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    try:
        with urllib.request.urlopen(url) as r:
            content = r.read().decode("utf-8")
        with open(dest, "w", encoding="utf-8") as f:
            f.write(content)
        ok.append(rel_path)
        print(f"  ✓  {rel_path}")
    except Exception as e:
        failed.append(rel_path)
        print(f"  ✗  {rel_path} — {e}")

print(f"\n{len(ok)} files updated, {len(failed)} failed.")
if not failed:
    print("Run python run.py to start the agent.")
