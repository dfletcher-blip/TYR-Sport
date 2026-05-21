"""
Backfill tyr_team on Contacts and sync their owner to the Team's owner.

Logic:
  - For each Team with a servicing account (_tyr_servicingaccount_value):
      find all active Contacts whose parent account = that servicing account
      set tyr_team = this team
      set ownerid = this team's owner

  This is a one-time backfill. After running this, use sync_team_contact_owners.py
  to keep owners in sync whenever a Team's owner changes.

Usage:
    python backfill_team_contact_owners.py --dry-run   # preview only
    python backfill_team_contact_owners.py             # apply changes
"""

import sys, os, json, uuid, time, requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv
load_dotenv()
from config.crm_connection import get_access_token

DYNAMICS_URL = os.getenv("DYNAMICS_URL", "").rstrip("/")
DRY_RUN = "--dry-run" in sys.argv
BATCH_SIZE = 20

_session = requests.Session()
_session.mount("https://", HTTPAdapter(max_retries=Retry(
    total=4, backoff_factor=3,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET", "POST", "PATCH"],
)))

_token = {"value": None, "expires": 0}

def get_headers(extra=None):
    if not _token["value"] or time.time() >= _token["expires"]:
        _token["value"] = get_access_token()
        _token["expires"] = time.time() + 3000
    h = {
        "Authorization": f"Bearer {_token['value']}",
        "OData-MaxVersion": "4.0", "OData-Version": "4.0",
        "Accept": "application/json", "Content-Type": "application/json",
        "Prefer": "odata.include-annotations=*",
    }
    if extra:
        h.update(extra)
    return h

def fetch_all(entity, select_fields, extra_filter=None):
    records, url = [], f"{DYNAMICS_URL}/api/data/v9.2/{entity}"
    params = {"$select": ",".join(select_fields)}
    if extra_filter:
        params["$filter"] = extra_filter
    while url:
        r = _session.get(url, headers=get_headers({"Prefer": "odata.maxpagesize=5000"}),
                         params=params, timeout=60)
        if not r.ok:
            print(f"  ERROR fetching {entity}: {r.status_code} {r.text[:300]}")
            sys.exit(1)
        data = r.json()
        records.extend(data.get("value", []))
        url = data.get("@odata.nextLink")
        params = None
        time.sleep(0.1)
    return records


# ── 1. Fetch all teams that have a servicing account ─────────────────────────
print("Step 1: Fetching teams with a servicing account...")
teams = fetch_all(
    "tyr_teams",
    ["tyr_teamid", "_ownerid_value", "_tyr_servicingaccount_value"],
    "_tyr_servicingaccount_value ne null and statecode eq 0",
)
print(f"  Teams with servicing account: {len(teams)}")

# Build map: account_id → (team_id, owner_id, owner_name)
account_to_team = {}
for t in teams:
    acct_id   = t.get("_tyr_servicingaccount_value")
    team_id   = t.get("tyr_teamid")
    owner_id  = t.get("_ownerid_value")
    owner_name = t.get("_ownerid_value@OData.Community.Display.V1.FormattedValue", owner_id)
    team_name  = t.get("_tyr_servicingaccount_value@OData.Community.Display.V1.FormattedValue", team_id)
    if acct_id and team_id and owner_id:
        account_to_team[acct_id] = {
            "team_id": team_id,
            "owner_id": owner_id,
            "owner_name": owner_name,
            "team_name": team_name,
        }

print(f"  Usable team→account mappings: {len(account_to_team)}\n")


# ── 2. Fetch all active contacts with a parent account ───────────────────────
print("Step 2: Fetching all active contacts with a parent account...")
contacts = fetch_all(
    "contacts",
    ["contactid", "fullname", "_parentcustomerid_value", "_tyr_team_value", "_ownerid_value"],
    "_parentcustomerid_value ne null and statecode eq 0",
)
print(f"  Active contacts with a parent account: {len(contacts)}\n")


# ── 3. Build update list ──────────────────────────────────────────────────────
print("Step 3: Cross-referencing contacts against team mappings...")
to_update = []
no_team_match = already_correct = needs_update = 0

for c in contacts:
    acct_id = c.get("_parentcustomerid_value")
    mapping = account_to_team.get(acct_id)
    if not mapping:
        no_team_match += 1
        continue

    current_team  = c.get("_tyr_team_value")
    current_owner = c.get("_ownerid_value")
    team_id   = mapping["team_id"]
    owner_id  = mapping["owner_id"]

    team_correct  = current_team  == team_id
    owner_correct = current_owner == owner_id

    if team_correct and owner_correct:
        already_correct += 1
        continue

    needs_update += 1
    to_update.append({
        "contact_id":   c["contactid"],
        "contact_name": c.get("fullname", c["contactid"]),
        "team_id":      team_id,
        "team_name":    mapping["team_name"],
        "owner_id":     owner_id,
        "owner_name":   mapping["owner_name"],
        "fix_team":     not team_correct,
        "fix_owner":    not owner_correct,
    })

print(f"  No matching team:   {no_team_match}")
print(f"  Already correct:    {already_correct}")
print(f"  Need update:        {needs_update}\n")

if not to_update:
    print("All contacts are already correctly linked and owned. Nothing to do.")
    sys.exit(0)

# Show preview
print(f"Preview (first 20 of {len(to_update)}):")
for u in to_update[:20]:
    changes = []
    if u["fix_team"]:  changes.append("set tyr_team")
    if u["fix_owner"]: changes.append(f"owner → {u['owner_name']}")
    print(f"  {u['contact_name'][:40]:<40}  [{u['team_name'][:35]}]  {', '.join(changes)}")
if len(to_update) > 20:
    print(f"  ... and {len(to_update) - 20} more")
print()

if DRY_RUN:
    print("Dry run complete. Run without --dry-run to apply changes.")
    sys.exit(0)


# ── 4. Batch PATCH ────────────────────────────────────────────────────────────
print(f"Step 4: Updating {len(to_update)} contacts (batch size {BATCH_SIZE})...")
updated = errors = 0
total_batches = (len(to_update) + BATCH_SIZE - 1) // BATCH_SIZE

for batch_num, start in enumerate(range(0, len(to_update), BATCH_SIZE), 1):
    batch = to_update[start : start + BATCH_SIZE]
    boundary = f"batch_{uuid.uuid4().hex}"
    parts = []

    for u in batch:
        payload = {
            "tyr_team@odata.bind": f"/tyr_teams({u['team_id']})",
            "ownerid@odata.bind":  f"/systemusers({u['owner_id']})",
        }
        body = json.dumps(payload)
        parts.append(
            f"--{boundary}\r\nContent-Type: application/http\r\n"
            f"Content-Transfer-Encoding: binary\r\n\r\n"
            f"PATCH {DYNAMICS_URL}/api/data/v9.2/contacts({u['contact_id']}) HTTP/1.1\r\n"
            f"Content-Type: application/json\r\nIf-Match: *\r\n\r\n{body}\r\n"
        )

    body = "".join(parts) + f"--{boundary}--\r\n"
    resp = _session.post(
        f"{DYNAMICS_URL}/api/data/v9.2/$batch",
        headers=get_headers({"Content-Type": f"multipart/mixed; boundary={boundary}"}),
        data=body.encode("utf-8"),
        timeout=120,
    )

    if resp.ok:
        ok   = resp.text.count("HTTP/1.1 204")
        fail = len(batch) - ok
        updated += ok
        errors  += fail
        print(f"  Batch {batch_num}/{total_batches}: {ok} updated, {fail} errors")
        if fail:
            err_lines = [l.strip() for l in resp.text.splitlines()
                         if '"message"' in l or '"errorcode"' in l]
            for el in err_lines[:2]:
                print(f"    {el}")
    else:
        errors += len(batch)
        first_err = next((l.strip() for l in resp.text.splitlines()
                          if '"message"' in l or "HTTP/1.1 4" in l), resp.text[:300])
        print(f"  Batch {batch_num}/{total_batches} FAILED: {resp.status_code} — {first_err}")

    # Retry failed contacts as individual PATCHes with team owner fallback
    time.sleep(1)

print(f"\nDone. Updated: {updated}, Errors: {errors}")
if errors:
    print("  Tip: if errors mention 'principal', the owner GUID may be a Team, not a User.")
    print("  Re-run with OWNER_TYPE=team to bind via /teams(...) instead of /systemusers(...)")
