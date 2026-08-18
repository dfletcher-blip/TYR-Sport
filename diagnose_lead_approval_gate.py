"""
Read-only diagnostic: find out how the Lead "Approval Status" / "Approver"
gate actually works, since it doesn't show up in the workflows-table
search used elsewhere in this repo (it's likely a Business Rule and/or
ribbon rule, not a classic Workflow/BPF/Flow).

Prints:
  1. The Lead fields with "approv" in the name (schema name, type, and
     option set values if it's a picklist).
  2. The raw definition of the 'Show Approved by after lead approval'
     Business Rule found earlier, so we can see what it actually checks.
  3. The current field values on a specific lead (search by name), plus
     its owner's manager, to see whether Approver looks manager-driven.

Makes NO changes. Safe to run any time.

Usage:
    python diagnose_lead_approval_gate.py [lead search term, default "Mulholland"]
"""
import sys, os, time, requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv
load_dotenv()
from config.crm_connection import get_access_token

DYNAMICS_URL = os.getenv("DYNAMICS_URL", "").rstrip("/")
LEAD_SEARCH = sys.argv[1] if len(sys.argv) > 1 else "Mulholland"

_session = requests.Session()
_retry = Retry(total=4, backoff_factor=3,
               status_forcelist=[429, 500, 502, 503, 504],
               allowed_methods=["GET"])
_session.mount("https://", HTTPAdapter(max_retries=_retry))
_session.mount("http://",  HTTPAdapter(max_retries=_retry))

_token = {"value": None, "expires": 0}

def get_headers(extra=None):
    if not _token["value"] or time.time() >= _token["expires"]:
        _token["value"] = get_access_token()
        _token["expires"] = time.time() + 3000
    h = {"Authorization": f"Bearer {_token['value']}",
         "OData-MaxVersion": "4.0", "OData-Version": "4.0",
         "Accept": "application/json", "Content-Type": "application/json",
         "Prefer": "odata.include-annotations=*"}
    if extra:
        h.update(extra)
    return h

def get(path, params=None):
    r = _session.get(f"{DYNAMICS_URL}/api/data/v9.2/{path}",
                     headers=get_headers(), params=params, timeout=30)
    if not r.ok:
        raise RuntimeError(f"GET {path} failed {r.status_code}: {r.text[:500]}")
    return r.json()

# ── 1. Find Lead fields related to approval ──────────────────────────────────
print("=" * 60)
print("1. Lead fields with 'approv' in the name")
print("=" * 60)
try:
    data = get("EntityDefinitions(LogicalName='lead')/Attributes")
    approval_fields = []
    for a in data.get("value", []):
        logical = a.get("LogicalName", "") or ""
        display = ((a.get("DisplayName") or {}).get("UserLocalizedLabel") or {}).get("Label", "") or ""
        if "approv" in logical.lower() or "approv" in display.lower():
            approval_fields.append(a)
            print(f"  {logical}  (\"{display}\")  type={a.get('AttributeType')}")
except RuntimeError as e:
    print(f"  ! Attribute lookup failed: {e}")
    approval_fields = []
print()

# ── 1b. Option set values for any picklist approval fields ──────────────────
CAST_TYPE = {
    "Picklist": "PicklistAttributeMetadata",
    "State": "StateAttributeMetadata",
    "Status": "StatusAttributeMetadata",
}
for a in approval_fields:
    if a.get("AttributeType") not in CAST_TYPE:
        continue
    logical = a.get("LogicalName")
    print(f"Option set values for '{logical}':")
    try:
        # OptionSet/GlobalOptionSet aren't included by default on this org's
        # single-record metadata GET (confirmed — the raw response had
        # neither key) — must be explicitly expanded.
        detail = get(
            f"EntityDefinitions(LogicalName='lead')/Attributes(LogicalName='{logical}')/Microsoft.Dynamics.CRM.{CAST_TYPE[a['AttributeType']]}",
            {"$expand": "OptionSet,GlobalOptionSet"},
        )
        options = ((detail.get("OptionSet") or {}).get("Options")) or \
                  ((detail.get("GlobalOptionSet") or {}).get("Options")) or []
        for o in options:
            label = ((o.get("Label") or {}).get("UserLocalizedLabel") or {}).get("Label", "")
            print(f"    {o.get('Value')} = {label}")
        if not options:
            # Still nothing — dump the top-level keys so we can see the
            # actual response shape instead of guessing a third location.
            print(f"    (no options found — response top-level keys: {list(detail.keys())})")
    except RuntimeError as e:
        print(f"    ! Option set lookup failed: {e}")
    print()

# ── 2. The Business Rule found earlier ───────────────────────────────────────
print("=" * 60)
print("2. 'Show Approved by after lead approval' Business Rule")
print("=" * 60)
try:
    data = get("workflows", {
        "$select": "workflowid,name,statecode,statuscode,clientdata",
        "$filter": "primaryentity eq 'lead' and category eq 2",
    })
    rules = [w for w in data.get("value", []) if "approval" in w.get("name", "").lower()]
    if not rules:
        print("  No matching Business Rule found.")
    for r in rules:
        print(f"  {r['name']} — statecode={r.get('statecode')} statuscode={r.get('statuscode')}")
        clientdata = r.get("clientdata") or ""
        print(f"  clientdata ({len(clientdata)} chars):")
        print(f"  {clientdata[:2000]}")
        print()
except RuntimeError as e:
    print(f"  ! Business Rule lookup failed: {e}")
print()

# ── 3. This specific lead's field values ─────────────────────────────────────
print("=" * 60)
print(f"3. Lead matching '{LEAD_SEARCH}'")
print("=" * 60)
try:
    # 'Virtual' type attributes (e.g. *name shadow fields for lookups/picklists)
    # aren't directly selectable — the base field's formatted-value annotation
    # already gives us the human-readable label, so skip them here. Lookup
    # fields must be selected as _<logicalname>_value, not the bare name
    # (that's what caused the previous 400 on tyr_approvedby).
    selectable_fields = [a for a in approval_fields if a.get("AttributeType") != "Virtual"]
    def select_name(a):
        return f"_{a['LogicalName']}_value" if a.get("AttributeType") == "Lookup" else a["LogicalName"]
    approval_field_names = ",".join(select_name(a) for a in selectable_fields) if selectable_fields else ""
    select = "leadid,fullname,companyname,statecode,_ownerid_value" + (f",{approval_field_names}" if approval_field_names else "")
    data = get("leads", {
        "$select": select,
        "$filter": f"contains(fullname,'{LEAD_SEARCH}')",
        "$top": 5,
    })
    # NOTE: no $expand on ownerid — it's a polymorphic lookup (user or team)
    # and Web API rejects $select=fullname against the abstract 'principal'
    # type. Read the owner name from the formatted-value annotation instead.
    leads = data.get("value", [])
    if not leads:
        print(f"  No lead found matching '{LEAD_SEARCH}'")
    for l in leads:
        print(f"  {l.get('fullname')} ({l.get('companyname')}) — {l.get('leadid')}")
        owner_id = l.get("_ownerid_value")
        owner_name = l.get("_ownerid_value@OData.Community.Display.V1.FormattedValue")
        print(f"    Owner: {owner_name} ({owner_id})")
        for a in selectable_fields:
            fld = select_name(a)
            val = l.get(fld)
            formatted = l.get(f"{fld}@OData.Community.Display.V1.FormattedValue")
            print(f"    {a['LogicalName']}: {formatted if formatted is not None else val}")
        print()

        # Owner's manager, in case Approver is meant to auto-populate from the
        # hierarchy. Only meaningful if the owner is a user, not a team —
        # if this 404s, the lead is probably team-owned.
        if owner_id:
            try:
                mgr_data = get(f"systemusers({owner_id})", {
                    "$select": "fullname",
                    "$expand": "parentsystemuserid($select=fullname,systemuserid)",
                })
                mgr = mgr_data.get("parentsystemuserid")
                print(f"    Owner's manager: {mgr.get('fullname') if mgr else '(none set)'}")
            except RuntimeError as e:
                print(f"    ! Owner manager lookup failed (owner may be a team, not a user): {e}")
except RuntimeError as e:
    print(f"  ! Lead lookup failed: {e}")
print()
print("Done. This is read-only -- nothing was changed.")
