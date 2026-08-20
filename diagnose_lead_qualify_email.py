"""
Read-only diagnostic: find what's actually sending the "lead is in the
hands of finance" email on Lead qualification.

Dillon reported this email still fires when using the new Convert to
Contact button -- even though that flow never touches tyr_approvalstatus
or the Submit For Approval process at all. That means the email is most
likely triggered by the Lead's state change to Qualified itself (which
our script does set via statuscode/statecode), not by the approval
field -- via a mechanism our earlier searches didn't check:
  1. Plugins (server-side C# code registered on Lead update/setstate) --
     invisible to the 'workflows' table searches used earlier.
  2. Power Automate flows registered with a different trigger shape than
     what we searched for before.

Makes NO changes. Safe to run any time.

Usage:
    python diagnose_lead_qualify_email.py
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

# ── 1. Modern Flows (Power Automate) on Lead, any trigger shape ─────────────
print("=" * 60)
print("1. All 'workflows' rows tied to lead (any category, no filter)")
print("=" * 60)
try:
    data = get("workflows", {
        "$select": "workflowid,name,statecode,statuscode,category,primaryentity",
        "$filter": "primaryentity eq 'lead'",
    })
    for w in data.get("value", []):
        cat_labels = {0: "Workflow", 1: "Dialog", 2: "BusinessRule", 3: "Action",
                      4: "BPF", 5: "ModernFlow", 6: "CustomApi"}
        cat = cat_labels.get(w.get("category"), str(w.get("category")))
        print(f"  [{cat}] {w['name']} — statecode={w.get('statecode')} statuscode={w.get('statuscode')}")
except RuntimeError as e:
    print(f"  ! failed: {e}")
print()

# ── 2. Plugin steps registered on Lead ───────────────────────────────────────
print("=" * 60)
print("2. Plugin steps (sdkmessageprocessingstep) registered on lead")
print("=" * 60)
try:
    data = get("sdkmessageprocessingsteps", {
        "$select": "sdkmessageprocessingstepid,name,stage,mode,statuscode,rank",
        "$filter": "primaryobjecttypecode eq 'lead'",
        "$expand": "sdkmessageid($select=name),plugintypeid($select=typename,assemblyname)",
    })
    steps = data.get("value", [])
    if not steps:
        print("  No plugin steps found on lead.")
    for s in steps:
        msg = (s.get("sdkmessageid") or {}).get("name", "?")
        plugin = s.get("plugintypeid") or {}
        stage_labels = {10: "PreValidation", 20: "PreOperation", 40: "PostOperation"}
        mode_labels = {0: "Synchronous", 1: "Asynchronous"}
        status_labels = {0: "Active", 1: "Inactive"}
        print(f"  {s.get('name')}")
        print(f"    Message: {msg}  Stage: {stage_labels.get(s.get('stage'), s.get('stage'))}"
              f"  Mode: {mode_labels.get(s.get('mode'), s.get('mode'))}"
              f"  Status: {status_labels.get(s.get('statuscode'), s.get('statuscode'))}")
        print(f"    Plugin type: {plugin.get('typename', '?')}  Assembly: {plugin.get('assemblyname', '?')}")
        print()
except RuntimeError as e:
    print(f"  ! failed: {e}")
print()

# ── 3. Email templates mentioning 'finance' ──────────────────────────────────
print("=" * 60)
print("3. Email templates with 'finance' in the name or subject")
print("=" * 60)
try:
    data = get("templates", {
        "$select": "templateid,title,subject,templatetypecode",
    })
    matches = [t for t in data.get("value", [])
               if "finance" in (t.get("title") or "").lower()
               or "finance" in (t.get("subject") or "").lower()]
    if not matches:
        print("  No matching templates found.")
    for t in matches:
        print(f"  {t.get('title')}  (entity: {t.get('templatetypecode')})")
        subj = t.get("subject") or ""
        print(f"    Subject: {subj[:200]}")
except RuntimeError as e:
    print(f"  ! failed: {e}")
print()
print("Done. This is read-only -- nothing was changed.")
