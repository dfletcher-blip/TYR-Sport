"""
Our Cloud Flow fixes didn't stop the crash on native Qualify Lead
(same lead, same errorCode 2147762970, tested after the flow was saved).
That means the crash is likely happening BEFORE our flow ever runs --
our flow triggers on Account row-created, so if Account creation itself
fails, our flow never fires.

Dataverse has a separate, built-in Lead -> Account field mapping used
specifically by native Qualify Lead (EntityMap / AttributeMap), totally
independent of any Cloud Flow. If tyr_tyrtype / tyr_businesstype are
mapped there as a raw, untranslated copy, that would explain a
synchronous crash during Account creation itself.

Checks for an EntityMap from lead -> account, and lists every
AttributeMap on it, flagging any that touch tyr_tyrtype, tyr_businesstype,
or cr4ae_accounttype.

Read-only. Makes no changes.

Usage:
    python diagnose_native_lead_account_mapping.py
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
print("1. EntityMap(s) from lead -> account")
print("=" * 70)
try:
    data = get("entitymaps", {
        "$select": "entitymapid,sourceentityname,targetentityname",
        "$filter": "sourceentityname eq 'lead' and targetentityname eq 'account'",
    })
    maps = data.get("value", [])
    if not maps:
        print("  ! No EntityMap found from lead -> account.")
    for m in maps:
        map_id = m.get("entitymapid")
        print(f"  entitymapid: {map_id}")
        print()
        print("  AttributeMaps:")
        try:
            attr_data = get("attributemaps", {
                "$select": "attributemapid,sourceattributename,targetattributename",
                "$filter": f"_entitymapid_value eq {map_id}",
            })
            attrs = attr_data.get("value", [])
        except RuntimeError as inner_e:
            print(f"    ! Filtered lookup failed ({inner_e}); falling back to unfiltered fetch + client-side match.")
            all_data = get("attributemaps", {
                "$select": "attributemapid,sourceattributename,targetattributename",
            })
            all_attrs = all_data.get("value", [])
            attrs = []
            for a in all_attrs:
                for k, v in a.items():
                    if "entitymapid" in k.lower() and str(v).lower() == str(map_id).lower():
                        attrs.append(a)
                        break
            if not attrs and all_attrs:
                print(f"    (Couldn't match by lookup value; here are the raw keys on one record for reference: {list(all_attrs[0].keys())})")
        if not attrs:
            print("    ! No AttributeMaps found for this EntityMap.")
        for a in attrs:
            src = a.get("sourceattributename", "")
            tgt = a.get("targetattributename", "")
            flag = " <-- WATCH THIS ONE" if src in ("tyr_tyrtype", "tyr_businesstype", "cr4ae_accounttype", "tyr_tyrentity") else ""
            print(f"    {src}  ->  {tgt}{flag}")
except RuntimeError as e:
    print(f"  ! Lookup failed: {e}")
print()

print("Done. This is read-only -- nothing was changed.")
