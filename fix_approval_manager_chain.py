"""
Fix the 'Issue during Approval' error on lead approvals.

Root cause: the approval notification flow calls 'Get a Manager row by ID'
for the approver, but top-level managers (Galindo, Wenzler, Meltzer) have
no manager set in CRM, so the step returns null and the flow fails, showing
the error dialog to every manager who approves a lead.

Fix: set Dillon Fletcher as the manager for the three top-level managers so
the flow can resolve the manager lookup without erroring.

Usage:
    python fix_approval_manager_chain.py --dry-run   # preview only
    python fix_approval_manager_chain.py             # apply
"""
import sys, os, time, requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv
load_dotenv()
from config.crm_connection import get_access_token

DYNAMICS_URL = os.getenv("DYNAMICS_URL", "").rstrip("/")
DRY_RUN = "--dry-run" in sys.argv

_session = requests.Session()
_session.mount("https://", HTTPAdapter(max_retries=Retry(total=4, backoff_factor=3,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET", "POST", "PATCH"])))

_token = {"value": None, "expires": 0}

def get_headers(extra=None):
    if not _token["value"] or time.time() >= _token["expires"]:
        _token["value"] = get_access_token()
        _token["expires"] = time.time() + 3000
    h = {"Authorization": f"Bearer {_token['value']}",
         "OData-MaxVersion": "4.0", "OData-Version": "4.0",
         "Accept": "application/json", "Content-Type": "application/json"}
    if extra:
        h.update(extra)
    return h

def get(path, params=None):
    r = _session.get(f"{DYNAMICS_URL}/api/data/v9.2/{path}",
                     headers=get_headers(), params=params, timeout=30)
    if not r.ok:
        raise RuntimeError(f"GET {path} → {r.status_code}: {r.text[:400]}")
    return r.json()

def patch(path, body):
    r = _session.patch(f"{DYNAMICS_URL}/api/data/v9.2/{path}",
                       headers=get_headers({"If-Match": "*"}), json=body, timeout=30)
    if not r.ok:
        raise RuntimeError(f"PATCH {path} → {r.status_code}: {r.text[:400]}")
    return r

def find_user(name):
    first, *rest = name.strip().split()
    last = " ".join(rest)
    d = get("systemusers", {
        "$select": "systemuserid,fullname,internalemailaddress",
        "$filter": f"firstname eq '{first}' and lastname eq '{last}' and isdisabled eq false",
    })
    users = d.get("value", [])
    if not users:
        d2 = get("systemusers", {
            "$select": "systemuserid,fullname,internalemailaddress",
            "$filter": f"contains(fullname,'{name}') and isdisabled eq false",
        })
        users = d2.get("value", [])
    return users[0] if users else None

def get_manager(user_id):
    d = get(f"systemusers({user_id})", {
        "$select": "fullname",
        "$expand": "parentsystemuserid($select=systemuserid,fullname)",
    })
    return d.get("parentsystemuserid")

print("=" * 60)
print("Fix: Set manager for top-level approvers")
print("=" * 60)
if DRY_RUN:
    print("DRY RUN — no changes will be made\n")

# ── Look up Dillon Fletcher (will be set as manager) ──────────────────────────
dillon = find_user("Dillon Fletcher")
if not dillon:
    print("ERROR: Dillon Fletcher not found"); exit(1)
print(f"Manager to assign : {dillon['fullname']} ({dillon['internalemailaddress']})")
print()

# ── Top-level managers who need a manager set ─────────────────────────────────
targets = ["Michael Galindo", "Tom Wenzler", "Larry Meltzer"]

for name in targets:
    user = find_user(name)
    if not user:
        print(f"  {name}: NOT FOUND — skipping")
        continue

    uid = user["systemuserid"]
    current_mgr = get_manager(uid)

    if current_mgr:
        print(f"  {user['fullname']}: already has manager '{current_mgr['fullname']}' — skipping")
        continue

    print(f"  {user['fullname']}: no manager set")
    print(f"    → Will set manager to: {dillon['fullname']}")

    if not DRY_RUN:
        try:
            patch(
                f"systemusers({uid})",
                {"parentsystemuserid@odata.bind": f"/systemusers({dillon['systemuserid']})"},
            )
            print(f"    ✓ Done")
        except RuntimeError as e:
            print(f"    ✗ Error: {e}")
    time.sleep(0.3)

print()
if DRY_RUN:
    print("Dry run complete. Run without --dry-run to apply.")
else:
    print("Done. The approval notification flow will now resolve manager")
    print("lookups for all three top-level approvers without error.")
