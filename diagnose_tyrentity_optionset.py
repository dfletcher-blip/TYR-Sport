"""
Follow-up to diagnose_optionset_mismatch.py -- check the 'TYR Entity'
field specifically (wasn't caught by the 'type'/'business' keyword
search), since it's currently showing correct values (EUR on both Lead
and Account) but we don't yet know whether that correctness depends on
the same flow we're about to stop relying on for TYR Type/Business Type.

Prints the field's exact logical name and its option set on both
entities, same comparison as the other diagnostic.

Read-only. Makes no changes.

Usage:
    python diagnose_tyrentity_optionset.py
"""
import os, time, requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv
load_dotenv()
from config.crm_connection import get_access_token

DYNAMICS_URL = os.getenv("DYNAMICS_URL", "").rstrip("/")

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

# ── 1. Find the field's logical name on each entity ──────────────────────────
field_names = {}
for entity in ["lead", "account"]:
    print("=" * 60)
    print(f"'{entity}' fields matching 'entity'")
    print("=" * 60)
    data = get(f"EntityDefinitions(LogicalName='{entity}')/Attributes")
    matches = []
    for a in data.get("value", []):
        logical = a.get("LogicalName", "") or ""
        display = ((a.get("DisplayName") or {}).get("UserLocalizedLabel") or {}).get("Label", "") or ""
        if "entity" in logical.lower() and logical.lower() != entity.lower():
            matches.append(a)
            print(f"  {logical}  (\"{display}\")  type={a.get('AttributeType')}")
    field_names[entity] = matches
    print()

# ── 2. Print option values for whatever field looks like TYR Entity ─────────
for entity in ["lead", "account"]:
    candidates = [a for a in field_names[entity]
                  if "tyr" in a.get("LogicalName", "").lower()]
    if not candidates:
        print(f"  ! No 'tyr_*entity*' field found on {entity}")
        continue
    field = candidates[0]["LogicalName"]
    print("=" * 60)
    print(f"{entity}.{field} option values")
    print("=" * 60)
    try:
        detail = None
        for cast in ("PicklistAttributeMetadata", "MultiSelectPicklistAttributeMetadata"):
            try:
                detail = get(
                    f"EntityDefinitions(LogicalName='{entity}')/Attributes(LogicalName='{field}')/Microsoft.Dynamics.CRM.{cast}",
                    {"$expand": "OptionSet,GlobalOptionSet"},
                )
                break
            except RuntimeError:
                continue
        if detail is None:
            print("  ! Could not fetch option set metadata.")
            continue
        options = ((detail.get("OptionSet") or {}).get("Options")) or \
                  ((detail.get("GlobalOptionSet") or {}).get("Options")) or []
        for o in options:
            label = ((o.get("Label") or {}).get("UserLocalizedLabel") or {}).get("Label", "")
            print(f"    {o.get('Value')} = {label}")
    except RuntimeError as e:
        print(f"  ! Lookup failed: {e}")
    print()

print("Done. This is read-only -- nothing was changed.")
