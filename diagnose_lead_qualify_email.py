"""
Diagnostic: find what's sending a "with Finance" email when a Lead is
marked Qualified via the new Convert to Contact button
(tyr_convertLeadToContact.js).

That JS never touches tyr_approvalstatus and never calls Submit For
Approval -- it only sets the Lead's native statecode/statuscode to
Qualified via Xrm.WebApi.updateRecord. If an email still fires, something
else in this org is reacting to that native state change directly.

The likely mechanism is a PLUGIN (compiled .NET code registered on the
Lead's Update message), which lives in the sdkmessageprocessingstep
table -- a completely different place than the classic Workflows/BPFs/
Flows (the 'workflows' table) that were checked earlier this session,
which is why nothing showed up in those earlier searches.

Read-only. Makes no changes.

Usage:
    python diagnose_lead_qualify_email.py
"""
import sys, os, time, requests
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

# ── 1. Plugin steps registered on Lead's Update message ─────────────────────
print("=" * 60)
print("1. Plugin steps (sdkmessageprocessingstep) on Lead Update")
print("=" * 60)
try:
    data = get("sdkmessageprocessingsteps", {
        "$select": "sdkmessageprocessingstepid,name,stage,mode,statecode,filteringattributes,rank",
        "$filter": "sdkmessageid/name eq 'Update' and sdkmessagefilterid/primaryobjecttypecode eq 'lead'",
        "$expand": "eventhandler_plugintypeid($select=typename,assemblyname)",
    })
    steps = data.get("value", [])
    if not steps:
        print("  No plugin steps found registered on Lead Update.")
    for s in steps:
        plugin = s.get("eventhandler_plugintypeid") or {}
        state_label = "Active" if s.get("statecode") == 0 else "Inactive"
        print(f"  {s.get('name')}")
        print(f"    Plugin: {plugin.get('typename')} ({plugin.get('assemblyname')})")
        print(f"    Stage: {s.get('stage')}  Mode: {s.get('mode')}  State: {state_label}")
        print(f"    Filtering attributes: {s.get('filteringattributes')}")
        print()
except RuntimeError as e:
    print(f"  ! Query failed: {e}")
    print("  Trying without $expand (in case that navigation property name is wrong here)...")
    try:
        data = get("sdkmessageprocessingsteps", {
            "$select": "sdkmessageprocessingstepid,name,stage,mode,statecode,filteringattributes,rank",
            "$filter": "sdkmessageid/name eq 'Update' and sdkmessagefilterid/primaryobjecttypecode eq 'lead'",
        })
        steps = data.get("value", [])
        if not steps:
            print("  No plugin steps found registered on Lead Update.")
        for s in steps:
            state_label = "Active" if s.get("statecode") == 0 else "Inactive"
            print(f"  {s.get('name')} -- stage={s.get('stage')} mode={s.get('mode')} state={state_label}")
            print(f"    Filtering attributes: {s.get('filteringattributes')}")
    except RuntimeError as e2:
        print(f"  ! Fallback also failed: {e2}")
print()

# ── 2. Email templates mentioning Finance ────────────────────────────────────
print("=" * 60)
print("2. Email templates with 'finance' in the title")
print("=" * 60)
try:
    data = get("templates", {"$select": "templateid,title,languagecode"})
    matches = [t for t in data.get("value", []) if "finance" in (t.get("title") or "").lower()]
    if not matches:
        print("  No email templates with 'finance' in the title.")
    for t in matches:
        print(f"  {t.get('title')} -- {t.get('templateid')}")
except RuntimeError as e:
    print(f"  ! Template lookup failed: {e}")
print()

# ── 3. Recent 'Finance' emails, to see what's actually being sent ───────────
print("=" * 60)
print("3. Recent emails with 'finance' in the subject (last 5)")
print("=" * 60)
try:
    data = get("emails", {
        "$select": "activityid,subject,createdon,_regardingobjectid_value",
        "$filter": "contains(tolower(subject),'finance')",
        "$orderby": "createdon desc",
        "$top": 5,
    })
    emails = data.get("value", [])
    if not emails:
        print("  No emails found with 'finance' in the subject.")
    for e in emails:
        regarding_name = e.get("_regardingobjectid_value@OData.Community.Display.V1.FormattedValue")
        print(f"  \"{e.get('subject')}\" -- {e.get('createdon')}")
        print(f"    Regarding: {regarding_name} ({e.get('_regardingobjectid_value')})")
except RuntimeError as e:
    print(f"  ! Email lookup failed: {e}")
print()

print("Done. This is read-only -- nothing was changed.")
