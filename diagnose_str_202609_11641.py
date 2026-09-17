"""
Trace ST-202609-11641 -- the specific Special Terms record where Tom
Wenzler should have been notified but wasn't.

Rather than guessing entity set/plural names, first resolves the real
entity logical names + entity set names for "Special Terms" and
"Special Terms Approval" via EntityDefinitions metadata (same approach
as diagnose_missing_special_terms_approval.py used earlier).

Finds:
  1. The Special Terms record itself -- who created it (submitter).
  2. Its related Special Terms Approval record(s) -- approval status,
     any approver/manager field set there.
  3. The submitter's systemuser record -- who their actual manager
     (parentsystemuserid) is, since 'Special Terms : Submit for
     Approval' emails whoever THAT resolves to, which may not match
     any 'Approver' field on the record itself.

Read-only. Makes no changes.

Usage:
    python diagnose_str_202609_11641.py
"""
import os, time, json, requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv
load_dotenv()
from config.crm_connection import get_access_token

DYNAMICS_URL = os.getenv("DYNAMICS_URL", "").rstrip("/")
RECORD_NAME = "ST-202609-11641"

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

def truncate(val, n=1200):
    s = json.dumps(val, indent=2) if not isinstance(val, str) else val
    return s[:n] + ("...(truncated)" if len(s) > n else "")

# ── 0. Resolve real entity names ─────────────────────────────────────────────
print("=" * 70)
print("0. Resolving entity logical/set names for 'Special Terms' entities")
print("=" * 70)
entity_data = get("EntityDefinitions", {"$select": "LogicalName,DisplayName,EntitySetName,PrimaryNameAttribute"})
main_entity = None
approval_entity = None
for e in entity_data.get("value", []):
    display = ((e.get("DisplayName") or {}).get("UserLocalizedLabel") or {}).get("Label", "") or ""
    if "special terms" in display.lower():
        print(f"  {e.get('LogicalName')}  (\"{display}\")  set={e.get('EntitySetName')}  primary={e.get('PrimaryNameAttribute')}")
        if "approval" in display.lower():
            approval_entity = e
        else:
            main_entity = e
print()

if not main_entity:
    print("! Could not resolve the main Special Terms entity. Stopping.")
    raise SystemExit(1)

main_set = main_entity["EntitySetName"]
main_logical = main_entity["LogicalName"]
main_primary = main_entity["PrimaryNameAttribute"]
approval_set = approval_entity["EntitySetName"] if approval_entity else None
approval_logical = approval_entity["LogicalName"] if approval_entity else None

# ── 1. Find the Special Terms record ─────────────────────────────────────────
print("=" * 70)
print(f"1. Special Terms record '{RECORD_NAME}' via {main_set}.{main_primary}")
print("=" * 70)
st_record = None
data = get(main_set, {
    "$select": "*",
    "$filter": f"{main_primary} eq '{RECORD_NAME}'",
    "$top": 1,
})
if data.get("value"):
    st_record = data["value"][0]
    print(f"  Found.")
    print(f"  raw record (truncated): {truncate(st_record, 1500)}")
else:
    print(f"  ! Not found via primary field '{main_primary}'. Trying tyr_name / name fallback...")
    for fallback_field in ("tyr_name", "name"):
        data = get(main_set, {"$select": "*", "$filter": f"{fallback_field} eq '{RECORD_NAME}'", "$top": 1})
        if data.get("value"):
            st_record = data["value"][0]
            print(f"  Found via '{fallback_field}'.")
            print(f"  raw record (truncated): {truncate(st_record, 1500)}")
            break
print()

createdby_id = st_record.get("_createdby_value") if st_record else None
print(f"  _createdby_value (submitter): {createdby_id}")
print()

# ── 2. Find related Special Terms Approval record(s) ─────────────────────────
print("=" * 70)
print(f"2. Related {approval_entity.get('DisplayName', {}).get('UserLocalizedLabel', {}).get('Label') if approval_entity else 'Approval'} record(s)")
print("=" * 70)
if st_record and approval_set:
    st_id_field = f"{main_logical}id"
    st_id = st_record.get(st_id_field)
    print(f"  Special Terms record id ({st_id_field}): {st_id}")
    if st_id:
        # Discover the lookup field on the approval entity that points back
        # to the main Special Terms entity, via its attribute metadata.
        approval_attrs = get(f"EntityDefinitions(LogicalName='{approval_logical}')/Attributes", {
            "$select": "LogicalName,AttributeType",
        })
        lookup_candidates = [a["LogicalName"] for a in approval_attrs.get("value", [])
                              if a.get("AttributeType") == "Lookup" and main_logical.split("_")[-1] in a["LogicalName"].lower()]
        print(f"  Candidate lookup fields on approval entity: {lookup_candidates}")
        found_any = False
        for lookup_field in lookup_candidates or ["tyr_specialterms"]:
            try:
                data = get(approval_set, {
                    "$select": "*",
                    "$filter": f"_{lookup_field}_value eq {st_id}",
                    "$top": 5,
                })
                if data.get("value"):
                    found_any = True
                    for r in data["value"]:
                        print(f"  Approval record: {truncate(r, 1500)}")
            except RuntimeError as e:
                print(f"  ! lookup via '{lookup_field}' failed: {e}")
        if not found_any:
            print("  ! No related approval records found.")
print()

# ── 3. Submitter's manager chain ─────────────────────────────────────────────
print("=" * 70)
print("3. Submitter's systemuser record + manager")
print("=" * 70)
if createdby_id:
    try:
        user = get(f"systemusers({createdby_id})", {
            "$select": "systemuserid,fullname,internalemailaddress,_parentsystemuserid_value",
        })
        print(f"  Submitter: {user.get('fullname')}  ({user.get('internalemailaddress')})")
        manager_id = user.get("_parentsystemuserid_value")
        print(f"  _parentsystemuserid_value (manager): {manager_id}")
        if manager_id:
            manager = get(f"systemusers({manager_id})", {
                "$select": "systemuserid,fullname,internalemailaddress",
            })
            print(f"  Manager resolves to: {manager.get('fullname')}  ({manager.get('internalemailaddress')})")
        else:
            print("  ! Submitter has NO manager set on their systemuser record.")
            print("    This would make 'Get a Manager row by ID' resolve to nothing,")
            print("    which explains a missing notification.")
    except RuntimeError as e:
        print(f"  ! Lookup failed: {e}")
else:
    print("  ! No submitter id available (record not found above).")

print()
print("Done. This is read-only -- nothing was changed.")
