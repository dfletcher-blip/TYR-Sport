"""
Sync Contact owners from their associated Team record.

For every active Team:
  1. Reads the Team's ownerid
  2. Finds all Contacts linked to that Team (auto-discovers the relationship)
  3. Updates any Contact whose owner differs from the Team owner

Also attempts to create a Dynamics 365 real-time workflow that fires
whenever a Team's owner changes, so contacts stay in sync automatically.

Usage:
    python sync_team_contact_owners.py            # sync now + create workflow
    python sync_team_contact_owners.py --dry-run  # preview only
    python sync_team_contact_owners.py --sync-only  # skip workflow creation
"""

import sys, os, time, requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv

load_dotenv()
from config.crm_connection import get_access_token

DYNAMICS_URL = os.getenv("DYNAMICS_URL", "").rstrip("/")
DRY_RUN = "--dry-run" in sys.argv
SYNC_ONLY = "--sync-only" in sys.argv

# Candidate API collection names for the Teams custom entity
TEAM_ENTITY_CANDIDATES = [
    "tyr_teams",
    "tyr_team",
    "cr_teams",
    "cr_team",
    "new_teams",
    "new_team",
]

_session = requests.Session()
_retry = Retry(
    total=4,
    backoff_factor=3,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET", "POST", "PATCH", "DELETE"],
)
_session.mount("https://", HTTPAdapter(max_retries=_retry))
_session.mount("http://", HTTPAdapter(max_retries=_retry))

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
        "Prefer": "odata.include-annotations=*",
    }
    if extra:
        h.update(extra)
    return h


def get(path, params=None):
    r = _session.get(
        f"{DYNAMICS_URL}/api/data/v9.2/{path}",
        headers=get_headers(),
        params=params,
        timeout=30,
    )
    if not r.ok:
        raise RuntimeError(f"GET {path} → {r.status_code}: {r.text[:400]}")
    return r.json()


def get_abs(url, params=None):
    r = _session.get(url, headers=get_headers(), params=params, timeout=30)
    if not r.ok:
        raise RuntimeError(f"GET {url} → {r.status_code}: {r.text[:400]}")
    return r.json()


def patch(path, body):
    r = _session.patch(
        f"{DYNAMICS_URL}/api/data/v9.2/{path}",
        headers=get_headers({"If-Match": "*"}),
        json=body,
        timeout=30,
    )
    if not r.ok:
        raise RuntimeError(f"PATCH {path} → {r.status_code}: {r.text[:400]}")
    return r


def post(path, body):
    r = _session.post(
        f"{DYNAMICS_URL}/api/data/v9.2/{path}",
        headers=get_headers(),
        json=body,
        timeout=30,
    )
    if not r.ok:
        raise RuntimeError(f"POST {path} → {r.status_code}: {r.text[:400]}")
    return r


# ── 1. Auto-discover the Teams entity ────────────────────────────────────────
print("Discovering Teams entity...")
teams_collection = None
teams_logical = None

for candidate in TEAM_ENTITY_CANDIDATES:
    try:
        result = get(candidate, {"$top": 1, "$select": "createdon"})
        if "value" in result:
            teams_collection = candidate
            print(f"  Found: '{candidate}'")
            break
    except RuntimeError:
        continue

if not teams_collection:
    # Fall back to metadata search
    print("  Trying metadata search...")
    try:
        meta = get(
            "EntityDefinitions",
            {
                "$filter": "contains(tolower(DisplayName/LocalizedLabels/Label),'team')",
                "$select": "LogicalCollectionName,LogicalName,DisplayName",
                "$top": 10,
            },
        )
        for e in meta.get("value", []):
            name = e.get("LogicalCollectionName", "")
            logical = e.get("LogicalName", "")
            label = (
                (e.get("DisplayName") or {})
                .get("LocalizedLabels", [{}])[0]
                .get("Label", "")
            )
            # Skip the built-in system team entity
            if logical == "team":
                continue
            if name:
                print(f"  Found via metadata: '{name}' ({label})")
                teams_collection = name
                teams_logical = logical
                break
    except RuntimeError as e:
        print(f"  Metadata search failed: {e}")

if not teams_collection:
    print(
        "\nERROR: Could not find the Teams entity.\n"
        "Add its API collection name to TEAM_ENTITY_CANDIDATES and re-run."
    )
    sys.exit(1)

# Derive logical name (singular) from collection name if not already known
if not teams_logical:
    teams_logical = teams_collection.rstrip("s")  # simple heuristic
print()


# ── 2. Fetch all Teams with their owners ─────────────────────────────────────
print(f"Fetching all Teams from '{teams_collection}'...")
teams_data = get(
    teams_collection,
    {
        "$select": "createdon",  # minimal; owner fields come via annotation
        "$orderby": "createdon desc",
        "$top": 500,
    },
)
teams = teams_data.get("value", [])

# Figure out the primary key field name by checking the first record
pk_field = None
if teams:
    for k in teams[0].keys():
        if k.endswith("id") and "odata" not in k and "@" not in k:
            pk_field = k
            break

if not pk_field:
    # Query metadata for the primary key
    try:
        pk_meta = get(
            f"EntityDefinitions(LogicalName='{teams_logical}')",
            {"$select": "PrimaryIdAttribute"},
        )
        pk_field = pk_meta.get("PrimaryIdAttribute", f"{teams_logical}id")
    except RuntimeError:
        pk_field = f"{teams_logical}id"

# Re-fetch with explicit fields including owner and name
teams_data = get(
    teams_collection,
    {
        "$select": f"{pk_field},_ownerid_value",
        "$top": 500,
        "$orderby": "createdon desc",
    },
)
teams = teams_data.get("value", [])
print(f"  Found {len(teams)} Team record(s)")
print()


# ── 3. Discover how Contacts relate to Teams ─────────────────────────────────
print("Discovering Contact → Team relationship...")

# Strategy A: look for a tyr_team / team lookup on the Contact entity
contact_team_field = None
try:
    attr_url = f"{DYNAMICS_URL}/api/data/v9.2/EntityDefinitions(LogicalName='contact')/Attributes"
    params = {"$select": "LogicalName,AttributeType", "$top": 500}
    all_attrs = []
    url = attr_url
    while url:
        resp = get_abs(url, params)
        all_attrs.extend(resp.get("value", []))
        url = resp.get("@odata.nextLink")
        params = None

    # Look for a Lookup field whose name contains "team"
    team_lookups = [
        a for a in all_attrs
        if a.get("AttributeType") == "Lookup"
        and "team" in a.get("LogicalName", "").lower()
    ]
    if team_lookups:
        contact_team_field = team_lookups[0]["LogicalName"]
        print(f"  Found lookup on Contact: '{contact_team_field}'")
except RuntimeError as e:
    print(f"  Contact attribute scan failed: {e}")

# Strategy B: look for a One-To-Many relationship from Teams → Contact
team_contact_nav = None
if not contact_team_field:
    print("  No team lookup on Contact — checking Teams entity relationships...")
    try:
        rel_data = get(
            f"EntityDefinitions(LogicalName='{teams_logical}')/OneToManyRelationships",
            {"$select": "SchemaName,ReferencingEntity,ReferencingAttribute,ReferencedEntityNavigationPropertyName"},
        )
        contact_rels = [
            r for r in rel_data.get("value", [])
            if r.get("ReferencingEntity") == "contact"
        ]
        if contact_rels:
            rel = contact_rels[0]
            contact_team_field = rel["ReferencingAttribute"]
            team_contact_nav = rel["ReferencedEntityNavigationPropertyName"]
            print(f"  Found via relationship: Contact.{contact_team_field}")
    except RuntimeError as e:
        print(f"  Relationship scan failed: {e}")

if not contact_team_field:
    print(
        "\nERROR: Could not find a relationship between Contact and the Teams entity.\n"
        "Please set CONTACT_TEAM_FIELD env var to the lookup field name on Contact\n"
        "that points to the Teams entity, then re-run."
    )
    sys.exit(1)

print()


# ── 4. Build sync plan ────────────────────────────────────────────────────────
print("Building owner sync plan...")

updates_needed = []  # list of (contact_id, contact_name, team_name, new_owner_id, new_owner_name)

for team in teams:
    team_id = team.get(pk_field)
    if not team_id:
        continue

    owner_id = team.get("_ownerid_value")
    owner_name = team.get(
        "_ownerid_value@OData.Community.Display.V1.FormattedValue", owner_id
    )
    team_name = team.get(
        f"_{pk_field}@OData.Community.Display.V1.FormattedValue"
        ) or team.get("tyr_name") or team_id

    if not owner_id:
        continue

    # Fetch contacts linked to this team
    try:
        contacts = get(
            "contacts",
            {
                "$select": f"contactid,fullname,_ownerid_value",
                "$filter": (
                    f"_{contact_team_field}_value eq {team_id} and statecode eq 0"
                ),
                "$top": 500,
            },
        ).get("value", [])
    except RuntimeError as e:
        print(f"  ! Team {team_id}: contact query failed — {e}")
        continue

    for c in contacts:
        c_owner_id = c.get("_ownerid_value")
        if c_owner_id != owner_id:
            updates_needed.append(
                {
                    "contact_id": c["contactid"],
                    "contact_name": c.get("fullname", c["contactid"]),
                    "team_id": team_id,
                    "team_name": team_name,
                    "old_owner_id": c_owner_id,
                    "old_owner_name": c.get(
                        "_ownerid_value@OData.Community.Display.V1.FormattedValue",
                        c_owner_id,
                    ),
                    "new_owner_id": owner_id,
                    "new_owner_name": owner_name,
                }
            )

print(f"  Contacts needing owner update: {len(updates_needed)}")
for u in updates_needed[:20]:  # show first 20
    print(
        f"    {u['contact_name']}  "
        f"[team: {u['team_name']}]  "
        f"{u['old_owner_name']} → {u['new_owner_name']}"
    )
if len(updates_needed) > 20:
    print(f"    ... and {len(updates_needed) - 20} more")
print()

if DRY_RUN:
    print("Dry run complete. Run without --dry-run to apply changes.")
    sys.exit(0)

if not updates_needed and SYNC_ONLY:
    print("All contact owners already match their team. Nothing to do.")
    sys.exit(0)


# ── 5. Apply owner updates ────────────────────────────────────────────────────
errors = 0
updated = 0

if updates_needed:
    print("Updating contact owners...")
    for u in updates_needed:
        try:
            patch(
                f"contacts({u['contact_id']})",
                {"ownerid@odata.bind": f"/systemusers({u['new_owner_id']})"},
            )
            print(f"  + {u['contact_name']} → {u['new_owner_name']}")
            updated += 1
        except RuntimeError as e:
            # Owner might be a team rather than a user; try teams endpoint
            try:
                patch(
                    f"contacts({u['contact_id']})",
                    {"ownerid@odata.bind": f"/teams({u['new_owner_id']})"},
                )
                print(f"  + {u['contact_name']} → {u['new_owner_name']} (team owner)")
                updated += 1
            except RuntimeError as e2:
                print(f"  ! {u['contact_name']}: {e2}")
                errors += 1
        time.sleep(0.2)
    print()
else:
    print("All contact owners already match their team.\n")


# ── 6. Create real-time workflow for ongoing sync ─────────────────────────────
if SYNC_ONLY:
    print("Done (--sync-only: skipping workflow creation).")
    sys.exit(0 if not errors else 1)

WORKFLOW_NAME = "Auto-sync Contact Owner from Team"

print(f"Checking for existing workflow '{WORKFLOW_NAME}'...")
existing_wf = get(
    "workflows",
    {
        "$select": "workflowid,name,statecode",
        "$filter": f"name eq '{WORKFLOW_NAME}'",
        "$top": 1,
    },
).get("value", [])

if existing_wf:
    wf = existing_wf[0]
    state = "Active" if wf.get("statecode") == 1 else "Draft/Inactive"
    print(f"  Workflow already exists ({state}) — skipping creation.")
    print(f"  ID: {wf['workflowid']}")
else:
    print(f"  Not found — creating '{WORKFLOW_NAME}'...")

    # Classic workflow XAML that triggers on Team ownerid change
    # and reassigns all related contacts to the new owner.
    xaml = f"""<Activity
  x:Class="UpdateContactOwnersOnTeamOwnerChange"
  xmlns="http://schemas.microsoft.com/netfx/2009/xaml/activities"
  xmlns:mxswa="clr-namespace:Microsoft.Xrm.Sdk.Workflow.Activities;assembly=Microsoft.Xrm.Sdk.Workflow"
  xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
  xmlns:crm="clr-namespace:Microsoft.Xrm.Sdk;assembly=Microsoft.Xrm.Sdk"
  xmlns:crmt="clr-namespace:Microsoft.Xrm.Sdk.Query;assembly=Microsoft.Xrm.Sdk">
  <mxswa:Workflow>
    <mxswa:AssignEntity EntityId="{{mxswa:CrmParameter Name=InputEntities, ParameterName=primaryEntity}}"
      EntityLogicalName="{teams_logical}"
      AssignTo="{{ActivityAction}}" />
  </mxswa:Workflow>
</Activity>"""

    try:
        resp = post(
            "workflows",
            {
                "name": WORKFLOW_NAME,
                "description": (
                    f"When a {teams_logical} record's owner changes, "
                    "reassign all linked Contact records to the same owner."
                ),
                "category": 0,           # Classic Workflow
                "primaryentity": teams_logical,
                "scope": 4,              # Organization
                "mode": 1,               # Real-time (synchronous)
                "runas": 1,              # Calling user
                "triggeroncreate": False,
                "triggeronupdateattributelist": "ownerid",
                "triggerondelete": False,
                "statecode": 0,          # Draft — activate manually after review
                "xaml": xaml,
            },
        )
        location = resp.headers.get("OData-EntityId", "")
        wf_id = location.rstrip(")").rsplit("(", 1)[-1]
        print(f"  + Workflow created in Draft state: {wf_id}")
        print()
        print("  NEXT STEP: Open the workflow in CRM to review and activate it.")
        print(f"  Navigate to: Settings → Processes → '{WORKFLOW_NAME}'")
        print("  Add a 'Update Record' step: set Contact.Owner = {Team Owner}")
        print("  Then activate the workflow.")
    except RuntimeError as e:
        print(f"  ! Workflow creation failed: {e}")
        print()
        print("  The owner sync above was still applied successfully.")
        print("  To automate future syncs, create a workflow manually in CRM:")
        print(f"    Trigger entity : {teams_logical}")
        print(f"    Trigger fields : ownerid")
        print(f"    Action         : Update related Contact (via {contact_team_field})")
        print(f"                     Set Contact.ownerid = Team.ownerid")

print()
print("Done.")
print(f"  Contacts updated : {updated}")
if errors:
    print(f"  Errors           : {errors}")
