"""
Reassign owner on Leads and Contacts where TYR Entity = USA and
TYR Type includes Run Specialty, to the rep for their state's region.

Records currently owned by Brandon Sullivan or Bill Potter are left alone.

Region / rep / state map (as given):
  West (Region 1)     Marina Preiss       CA WA OR NV ID UT AZ MT WY CO NM AK HI
  Midwest (Region 2)  Caroline Kulp       IL VA MI IN WI MN IA MO KS NE SD ND AR WV KY DC
  South (Region 3)    Angela Nicolletta   TX OK LA MS AL TN FL GA SC NC
  Northeast (Region 4) Dan MacQuarrie     NY PA OH NJ MD DE CT MA RI NH VT ME

Safe by default: run with no flags to PREVIEW the planned changes.
Add --apply to actually write the owner changes.

Usage:
  python reassign_run_specialty_by_region.py            # dry run
  python reassign_run_specialty_by_region.py --apply    # do it for real
"""

import os
import json
import time
import uuid
import argparse
import requests
from dotenv import load_dotenv

load_dotenv()
from config.crm_connection import get_access_token

DYNAMICS_URL = os.getenv("DYNAMICS_URL", "").rstrip("/")

TYR_ENTITY_FIELD = "tyr_tyrentity"
TYR_TYPE_FIELD = "tyr_tyrtype"
TYR_ENTITY_TARGET_LABEL = "USA"
TYR_TYPE_TARGET_LABEL = "Run Specialty"

EXCLUDED_OWNER_NAMES = {"brandon sullivan", "bill potter"}

REGION_REPS = {
    "West (Region 1)": "Marina Preiss",
    "Midwest (Region 2)": "Caroline Kulp",
    "South (Region 3)": "Angela Nicolletta",
    "Northeast (Region 4)": "Dan MacQuarrie",
}

STATE_TO_REGION = {}


def _map_states(states, region):
    for s in states:
        STATE_TO_REGION[s] = region


_map_states(
    ["CA", "WA", "OR", "NV", "ID", "UT", "AZ", "MT", "WY", "CO", "NM", "AK", "HI"],
    "West (Region 1)",
)
_map_states(
    ["IL", "VA", "MI", "IN", "WI", "MN", "IA", "MO", "KS", "NE", "SD", "ND", "AR", "WV", "KY", "DC"],
    "Midwest (Region 2)",
)
_map_states(
    ["TX", "OK", "LA", "MS", "AL", "TN", "FL", "GA", "SC", "NC"],
    "South (Region 3)",
)
_map_states(
    ["NY", "PA", "OH", "NJ", "MD", "DE", "CT", "MA", "RI", "NH", "VT", "ME"],
    "Northeast (Region 4)",
)

STATE_FULLNAME_TO_ABBR = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "district of columbia": "DC", "florida": "FL", "georgia": "GA", "hawaii": "HI",
    "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
    "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
    "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI",
    "south carolina": "SC", "south dakota": "SD", "tennessee": "TN", "texas": "TX",
    "utah": "UT", "vermont": "VT", "virginia": "VA", "washington": "WA",
    "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
}

_token = {"value": None, "expires": 0}


def get_headers(extra=None):
    if not _token["value"] or time.time() >= _token["expires"]:
        _token["value"] = get_access_token()
        _token["expires"] = time.time() + 3000
    h = {
        "Authorization": f"Bearer {_token['value']}",
        "OData-MaxVersion": "4.0",
        "OData-Version": "4.0",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    if extra:
        h.update(extra)
    return h


def get_json(url, params=None):
    r = requests.get(url, headers=get_headers(), params=params, timeout=60)
    if not r.ok:
        raise RuntimeError(f"GET {url} failed ({r.status_code}): {r.text[:400]}")
    return r.json()


def get_attribute_type(entity_logical, field_logical):
    """Return AttributeType string for a field, or None if it doesn't exist on this entity."""
    r = requests.get(
        f"{DYNAMICS_URL}/api/data/v9.2/EntityDefinitions(LogicalName='{entity_logical}')"
        f"/Attributes(LogicalName='{field_logical}')",
        headers=get_headers(),
        params={"$select": "AttributeType"},
        timeout=30,
    )
    if not r.ok:
        return None
    return r.json().get("AttributeType")


def get_option_value(entity_logical, field_logical, attribute_type, target_label):
    """Find the numeric option value on entity_logical.field_logical whose label matches target_label."""
    cast = (
        "Microsoft.Dynamics.CRM.MultiSelectPicklistAttributeMetadata"
        if attribute_type == "MultiSelectPicklistType" or attribute_type == "MultiSelectPicklist"
        else "Microsoft.Dynamics.CRM.PicklistAttributeMetadata"
    )
    data = get_json(
        f"{DYNAMICS_URL}/api/data/v9.2/EntityDefinitions(LogicalName='{entity_logical}')"
        f"/Attributes/{cast}",
        {"$filter": f"LogicalName eq '{field_logical}'", "$expand": "OptionSet"},
    )
    items = data.get("value", [])
    if not items:
        return None
    options = (items[0].get("OptionSet") or {}).get("Options", [])
    target = target_label.strip().lower()

    exact = None
    partial = None
    for opt in options:
        label = ((opt.get("Label") or {}).get("UserLocalizedLabel") or {}).get("Label", "")
        low = label.strip().lower()
        if low == target:
            exact = opt.get("Value")
            break
        if target in low and partial is None:
            partial = opt.get("Value")
    return exact if exact is not None else partial


def find_user_by_name(fullname):
    data = get_json(
        f"{DYNAMICS_URL}/api/data/v9.2/systemusers",
        {"$select": "systemuserid,fullname", "$filter": f"fullname eq '{fullname}'"},
    )
    users = data.get("value", [])
    if not users:
        # fall back to contains-match in case of middle names / punctuation differences
        data = get_json(
            f"{DYNAMICS_URL}/api/data/v9.2/systemusers",
            {"$select": "systemuserid,fullname", "$filter": f"contains(fullname,'{fullname}')"},
        )
        users = data.get("value", [])
    if not users:
        return None
    return users[0]


def fetch_all(url, params):
    results = []
    headers_extra = {"Prefer": "odata.maxpagesize=1000"}
    while url:
        r = requests.get(url, headers=get_headers(headers_extra), params=params, timeout=60)
        if not r.ok:
            raise RuntimeError(f"GET {url} failed ({r.status_code}): {r.text[:400]}")
        data = r.json()
        results.extend(data.get("value", []))
        url = data.get("@odata.nextLink")
        params = None
        time.sleep(0.2)
    return results


def normalize_state(raw):
    if not raw:
        return None
    s = raw.strip()
    if not s:
        return None
    if len(s) == 2:
        abbr = s.upper()
        if abbr in STATE_TO_REGION:
            return abbr
    return STATE_FULLNAME_TO_ABBR.get(s.lower())


def build_plan(entity_set, entity_logical, id_field, name_field, entity_value, type_value, type_is_multi, reps_by_region):
    attr_filter_entity = f"{TYR_ENTITY_FIELD} eq {entity_value}"
    if type_is_multi:
        attr_filter_type = (
            f"Microsoft.Dynamics.CRM.ContainValues"
            f"(PropertyName='{TYR_TYPE_FIELD}',PropertyValues=['{type_value}'])"
        )
    else:
        attr_filter_type = f"{TYR_TYPE_FIELD} eq {type_value}"

    params = {
        "$select": f"{id_field},{name_field},address1_stateorprovince,_ownerid_value",
        "$filter": f"{attr_filter_entity} and {attr_filter_type}",
        "$expand": "ownerid($select=fullname)",
    }

    records = fetch_all(f"{DYNAMICS_URL}/api/data/v9.2/{entity_set}", params)

    plan = {
        "entity": entity_set,
        "total_matched": len(records),
        "excluded_owner": [],
        "unmapped_state": [],
        "already_correct": [],
        "to_reassign": [],
    }

    for rec in records:
        rid = rec.get(id_field)
        name = rec.get(name_field, "(no name)")
        owner = (rec.get("ownerid") or {}).get("fullname", "") or ""

        if owner.strip().lower() in EXCLUDED_OWNER_NAMES:
            plan["excluded_owner"].append({"id": rid, "name": name, "owner": owner})
            continue

        abbr = normalize_state(rec.get("address1_stateorprovince"))
        if not abbr:
            plan["unmapped_state"].append(
                {"id": rid, "name": name, "owner": owner, "state": rec.get("address1_stateorprovince")}
            )
            continue

        region = STATE_TO_REGION[abbr]
        rep_name, rep_id = reps_by_region[region]

        if owner.strip().lower() == rep_name.strip().lower():
            plan["already_correct"].append({"id": rid, "name": name, "owner": owner})
            continue

        plan["to_reassign"].append(
            {
                "id": rid,
                "name": name,
                "state": abbr,
                "region": region,
                "current_owner": owner,
                "new_owner": rep_name,
                "new_owner_id": rep_id,
            }
        )

    return plan


def apply_plan(entity_set, id_field, updates):
    """updates: list of {id, new_owner_id}. Returns (updated, errors)."""
    BATCH_SIZE = 50
    updated = 0
    error_list = []

    for start in range(0, len(updates), BATCH_SIZE):
        batch = updates[start:start + BATCH_SIZE]
        boundary = f"batch_{uuid.uuid4().hex}"
        parts = []
        for u in batch:
            body = json.dumps({"ownerid@odata.bind": f"/systemusers({u['new_owner_id']})"})
            parts.append(
                f"--{boundary}\r\nContent-Type: application/http\r\n"
                f"Content-Transfer-Encoding: binary\r\n\r\n"
                f"PATCH {DYNAMICS_URL}/api/data/v9.2/{entity_set}({u['id']}) HTTP/1.1\r\n"
                f"Content-Type: application/json\r\nIf-Match: *\r\n\r\n{body}\r\n"
            )
        batch_body = "".join(parts) + f"--{boundary}--\r\n"
        resp = requests.post(
            f"{DYNAMICS_URL}/api/data/v9.2/$batch",
            headers=get_headers({"Content-Type": f"multipart/mixed; boundary={boundary}"}),
            data=batch_body.encode("utf-8"),
            timeout=120,
        )
        if resp.ok:
            ok = resp.text.count("HTTP/1.1 204")
            updated += ok
            if ok < len(batch):
                error_list.append(f"Batch at {start}: {len(batch) - ok} failed — {resp.text[:300]}")
        else:
            error_list.append(f"Batch at {start} failed: {resp.status_code} {resp.text[:300]}")
        time.sleep(0.5)

    return updated, error_list


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Actually write owner changes (default is preview only)")
    args = parser.parse_args()

    print("=" * 70)
    print("Reassign Leads/Contacts (TYR Entity=USA, TYR Type=Run Specialty)")
    print("by region, skipping records owned by Brandon Sullivan or Bill Potter")
    print("=" * 70)

    # 1. Resolve reps' systemuserid
    print("\nLooking up reps...")
    reps_by_region = {}
    for region, rep_name in REGION_REPS.items():
        user = find_user_by_name(rep_name)
        if not user:
            print(f"  ERROR: could not find CRM user '{rep_name}' for {region}. Aborting.")
            return
        reps_by_region[region] = (user["fullname"], user["systemuserid"])
        print(f"  {region}: {user['fullname']} ({user['systemuserid']})")

    # 2. Resolve tyr_tyrentity 'USA' value and tyr_tyrtype 'Run Specialty' value per entity
    entity_plans = []
    for entity_set, entity_logical, id_field, name_field in [
        ("leads", "lead", "leadid", "fullname"),
        ("contacts", "contact", "contactid", "fullname"),
    ]:
        print(f"\n--- {entity_set} ---")

        entity_attr_type = get_attribute_type(entity_logical, TYR_ENTITY_FIELD)
        type_attr_type = get_attribute_type(entity_logical, TYR_TYPE_FIELD)

        if entity_attr_type is None or type_attr_type is None:
            print(
                f"  SKIPPING {entity_set}: field(s) not found on '{entity_logical}' "
                f"(tyr_tyrentity={'found' if entity_attr_type else 'MISSING'}, "
                f"tyr_tyrtype={'found' if type_attr_type else 'MISSING'})"
            )
            continue

        entity_value = get_option_value(entity_logical, TYR_ENTITY_FIELD, entity_attr_type, TYR_ENTITY_TARGET_LABEL)
        type_value = get_option_value(entity_logical, TYR_TYPE_FIELD, type_attr_type, TYR_TYPE_TARGET_LABEL)

        if entity_value is None:
            print(f"  SKIPPING {entity_set}: no '{TYR_ENTITY_TARGET_LABEL}' option found on {TYR_ENTITY_FIELD}")
            continue
        if type_value is None:
            print(f"  SKIPPING {entity_set}: no '{TYR_TYPE_TARGET_LABEL}' option found on {TYR_TYPE_FIELD}")
            continue

        type_is_multi = "MultiSelect" in type_attr_type
        print(f"  {TYR_ENTITY_FIELD}='{TYR_ENTITY_TARGET_LABEL}' -> {entity_value}")
        print(f"  {TYR_TYPE_FIELD}='{TYR_TYPE_TARGET_LABEL}' -> {type_value} (multi-select={type_is_multi})")

        plan = build_plan(
            entity_set, entity_logical, id_field, name_field,
            entity_value, type_value, type_is_multi, reps_by_region,
        )
        entity_plans.append((entity_set, id_field, plan))

    # 3. Report
    grand_total_reassign = 0
    for entity_set, id_field, plan in entity_plans:
        print(f"\n=== {entity_set} summary ===")
        print(f"  Total matched (USA / Run Specialty): {plan['total_matched']}")
        print(f"  Ignored (owned by Brandon Sullivan/Bill Potter): {len(plan['excluded_owner'])}")
        print(f"  Skipped (no mappable state): {len(plan['unmapped_state'])}")
        print(f"  Already correct owner: {len(plan['already_correct'])}")
        print(f"  To reassign: {len(plan['to_reassign'])}")
        grand_total_reassign += len(plan["to_reassign"])

        if plan["unmapped_state"]:
            print("  Sample unmapped-state records:")
            for r in plan["unmapped_state"][:5]:
                print(f"    - {r['name']} (owner={r['owner']!r}, state={r['state']!r})")

        if plan["to_reassign"]:
            by_rep = {}
            for r in plan["to_reassign"]:
                by_rep.setdefault(r["new_owner"], []).append(r)
            for rep, recs in by_rep.items():
                print(f"  -> {rep}: {len(recs)} record(s)")
                for r in recs[:10]:
                    print(f"       {r['name']} ({r['state']}), was: {r['current_owner'] or 'Unassigned'}")
                if len(recs) > 10:
                    print(f"       ... and {len(recs) - 10} more")

    if not args.apply:
        print(f"\nPREVIEW ONLY — {grand_total_reassign} record(s) would be reassigned.")
        print("Re-run with --apply to write these changes.")
        return

    # 4. Apply
    print(f"\nApplying changes to {grand_total_reassign} record(s)...")
    for entity_set, id_field, plan in entity_plans:
        if not plan["to_reassign"]:
            continue
        updates = [{"id": r["id"], "new_owner_id": r["new_owner_id"]} for r in plan["to_reassign"]]
        updated, errors = apply_plan(entity_set, id_field, updates)
        print(f"  {entity_set}: {updated} updated, {len(errors)} error batch(es)")
        for e in errors:
            print(f"    {e}")

    print("\nDone.")


if __name__ == "__main__":
    main()
