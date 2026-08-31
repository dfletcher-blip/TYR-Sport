"""
The Convert to Contact button just failed for every user with:
"An undeclared property 'tyr_lead' which only has property annotations
in the payload but no property value was found" -- meaning
"tyr_lead@odata.bind" is not the correct navigation property name for
that lookup on Account (my earlier assumption that it matches the
attribute logical name was wrong for this field).

Finds the real single-valued navigation property name to use for
@odata.bind on Account.tyr_lead, via the ManyToOneRelationships
(Account is the referencing/"many" side pointing at one Lead).

Read-only. Makes no changes.

Usage:
    python diagnose_tyr_lead_navproperty.py
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

print("=" * 70)
print("Account.tyr_lead ManyToOne relationship (navigation property for @odata.bind)")
print("=" * 70)
try:
    data = get("EntityDefinitions(LogicalName='account')/ManyToOneRelationships", {
        "$select": "SchemaName,ReferencingAttribute,ReferencingEntityNavigationPropertyName,ReferencedEntity",
        "$filter": "ReferencingAttribute eq 'tyr_lead'",
    })
    rels = data.get("value", [])
    if not rels:
        print("  ! No ManyToOne relationship found with ReferencingAttribute = 'tyr_lead'.")
    for r in rels:
        print(f"  SchemaName: {r.get('SchemaName')}")
        print(f"  ReferencingEntityNavigationPropertyName: {r.get('ReferencingEntityNavigationPropertyName')}")
        print(f"  ReferencedEntity: {r.get('ReferencedEntity')}")
        print()
        print(f"  ---> Use in JS as: \"{r.get('ReferencingEntityNavigationPropertyName')}@odata.bind\"")
except RuntimeError as e:
    print(f"  ! Lookup failed: {e}")

print()
print("Done. This is read-only -- nothing was changed.")
