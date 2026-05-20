"""
Grant Sales Rep users permission to edit email addresses on Contact records.

Two-pronged approach:
  1. Ensures the Sales Rep role has Write privilege on the Contact entity
     (Business Unit scope) via the AddPrivilegesRole action.
  2. Handles Field-Level Security on emailaddress1 / emailaddress2:
     - Finds or creates a "Sales Rep - Email Edit" Field Security Profile
     - Sets canread=true, cancreate=true, canupdate=true for both fields
     - Assigns the profile to all active users who hold the Sales Rep role

Usage:
    python update_sales_rep_email_permissions.py           # apply changes
    python update_sales_rep_email_permissions.py --dry-run # preview only
"""

import sys, os, time, requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv

load_dotenv()
from config.crm_connection import get_access_token

DYNAMICS_URL = os.getenv("DYNAMICS_URL", "").rstrip("/")
DRY_RUN = "--dry-run" in sys.argv

PROFILE_NAME = "Sales Rep - Email Edit"
EMAIL_FIELDS = ["emailaddress1", "emailaddress2"]

# Role names to match (case-insensitive substring match)
SALES_REP_ROLE_KEYWORDS = ["sales rep", "salesperson", "sales person"]

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
        raise RuntimeError(f"GET {path} failed {r.status_code}: {r.text[:400]}")
    return r.json()


def post(path, body):
    r = _session.post(
        f"{DYNAMICS_URL}/api/data/v9.2/{path}",
        headers=get_headers(),
        json=body,
        timeout=30,
    )
    if not r.ok:
        raise RuntimeError(f"POST {path} failed {r.status_code}: {r.text[:400]}")
    return r


def patch(path, body):
    r = _session.patch(
        f"{DYNAMICS_URL}/api/data/v9.2/{path}",
        headers=get_headers({"If-Match": "*"}),
        json=body,
        timeout=30,
    )
    if not r.ok:
        raise RuntimeError(f"PATCH {path} failed {r.status_code}: {r.text[:400]}")
    return r


# ── 1. Find Sales Rep security role(s) ───────────────────────────────────────
print("Looking up Sales Rep security role(s)...")
all_roles = get("roles", {"$select": "roleid,name", "$filter": "statecode eq 0"})
sales_roles = [
    r for r in all_roles.get("value", [])
    if any(kw in r["name"].lower() for kw in SALES_REP_ROLE_KEYWORDS)
]

if not sales_roles:
    print(
        "  No roles matched keywords: "
        + ", ".join(f'"{k}"' for k in SALES_REP_ROLE_KEYWORDS)
    )
    print("\n  All active roles in your org:")
    for r in sorted(all_roles.get("value", []), key=lambda x: x["name"]):
        print(f"    {r['name']}")
    print(
        "\nEdit SALES_REP_ROLE_KEYWORDS in this script to match your role name and re-run."
    )
    sys.exit(1)

print(f"  Found {len(sales_roles)} matching role(s):")
for r in sales_roles:
    print(f"    [{r['roleid']}] {r['name']}")
print()


# ── 2. Find active users with the Sales Rep role ──────────────────────────────
print("Finding active users with Sales Rep role(s)...")
sales_rep_users = []
seen_user_ids = set()

for role in sales_roles:
    role_id = role["roleid"]
    data = get(
        "systemusers",
        {
            "$select": "systemuserid,fullname,internalemailaddress",
            "$filter": (
                f"isdisabled eq false and "
                f"systemuserroles_association/any(r: r/roleid eq {role_id})"
            ),
        },
    )
    for u in data.get("value", []):
        if u["systemuserid"] not in seen_user_ids:
            seen_user_ids.add(u["systemuserid"])
            u["_role_name"] = role["name"]
            sales_rep_users.append(u)

if not sales_rep_users:
    print("  No active users found with the Sales Rep role.")
    print("  (Permissions on the role itself will still be updated.)")
else:
    print(f"  Found {len(sales_rep_users)} user(s):")
    for u in sales_rep_users:
        print(f"    {u['fullname']} <{u.get('internalemailaddress','')}>  [{u['_role_name']}]")
print()


# ── 3. Ensure Write privilege on Contact entity (entity-level) ─────────────
print("Checking Contact entity Write privilege for Sales Rep role(s)...")

# prvWriteContact depth codes: 0=None, 1=User, 2=BusinessUnit, 3=ParentChildBU, 4=Organization
DEPTH_LABELS = {0: "None", 1: "User", 2: "BusinessUnit", 3: "ParentChildBU", 4: "Organization"}
TARGET_DEPTH = 2  # BusinessUnit — sales reps can edit contacts in their BU

role_privilege_changes = []

for role in sales_roles:
    role_id = role["roleid"]
    # Query existing roleprivileges for this role
    try:
        priv_data = get(
            f"roles({role_id})/roleprivileges_association",
            {"$select": "privilegeid,name,_privilegedepthmask"},
        )
        existing = priv_data.get("value", [])
    except RuntimeError:
        existing = []

    write_priv = next((p for p in existing if p.get("name") == "prvWriteContact"), None)

    if write_priv:
        depth = write_priv.get("_privilegedepthmask", -1)
        label = DEPTH_LABELS.get(depth, str(depth))
        if depth == 0:
            print(f"  {role['name']}: prvWriteContact = {label} — NEEDS UPGRADE to BusinessUnit")
            role_privilege_changes.append((role, "upgrade"))
        else:
            print(f"  {role['name']}: prvWriteContact = {label} — OK")
    else:
        print(f"  {role['name']}: prvWriteContact not found — NEEDS ADDING at BusinessUnit")
        role_privilege_changes.append((role, "add"))

print()


# ── 4. Check Field-Level Security on email fields ─────────────────────────────
print("Checking Field-Level Security on email fields...")
fls_data = get(
    "fieldpermissions",
    {
        "$select": "fieldpermissionid,fieldsecurityprofileid,attributelogicalname,cancreate,canread,canupdate",
        "$filter": (
            "entityname eq 'contact' and ("
            + " or ".join(f"attributelogicalname eq '{f}'" for f in EMAIL_FIELDS)
            + ")"
        ),
    },
)
existing_fls = fls_data.get("value", [])

fls_active = len(existing_fls) > 0
if fls_active:
    print(f"  Field-Level Security IS active for email fields ({len(existing_fls)} record(s)):")
    for fp in existing_fls:
        profile_id = fp.get("_fieldsecurityprofileid_value") or fp.get("fieldsecurityprofileid")
        print(
            f"    field={fp['attributelogicalname']}  "
            f"read={fp['canread']}  create={fp['cancreate']}  update={fp['canupdate']}  "
            f"profile={profile_id}"
        )
else:
    print("  No Field-Level Security found for email fields — standard role privileges apply.")
print()


# ── 5. Find or create the Sales Rep Email Edit Field Security Profile ─────────
profile_id = None
profile_action = None

if fls_active:
    print(f"Locating Field Security Profile '{PROFILE_NAME}'...")
    profile_data = get(
        "fieldsecurityprofiles",
        {
            "$select": "fieldsecurityprofileid,name",
            "$filter": f"name eq '{PROFILE_NAME}'",
        },
    )
    profiles = profile_data.get("value", [])
    if profiles:
        profile_id = profiles[0]["fieldsecurityprofileid"]
        print(f"  Found existing profile: {profile_id}")
        profile_action = "existing"
    else:
        print(f"  Profile not found — will create '{PROFILE_NAME}'")
        profile_action = "create"
    print()


# ── Summary of planned changes ────────────────────────────────────────────────
print("=" * 60)
print("CHANGES TO APPLY")
print("=" * 60)

if role_privilege_changes:
    print(f"\n  Entity-level Contact Write privilege:")
    for role, action in role_privilege_changes:
        verb = "Add" if action == "add" else "Upgrade"
        print(f"    {verb} prvWriteContact (BusinessUnit) → {role['name']}")
else:
    print("\n  Entity-level Contact Write privilege: already OK on all roles")

if fls_active:
    if profile_action == "create":
        print(f"\n  Field Security Profile: CREATE '{PROFILE_NAME}'")
    else:
        print(f"\n  Field Security Profile: use existing '{PROFILE_NAME}'")

    print(f"\n  Field permissions (canread=True, cancreate=True, canupdate=True):")
    for field in EMAIL_FIELDS:
        print(f"    contact.{field}")

    if sales_rep_users:
        print(f"\n  Assign profile to {len(sales_rep_users)} user(s):")
        for u in sales_rep_users:
            print(f"    {u['fullname']}")
else:
    print("\n  Field-Level Security: not in use — no FLS changes needed")

print()

if not role_privilege_changes and not fls_active:
    print("Nothing to change — Sales Rep users already have full email edit permissions.")
    sys.exit(0)

if DRY_RUN:
    print("Dry run complete. Run without --dry-run to apply changes.")
    sys.exit(0)

# ── Apply changes ─────────────────────────────────────────────────────────────
errors = 0

# 5a. Fix entity-level Contact Write privilege
if role_privilege_changes:
    print("Updating entity-level Contact Write privilege...")
    for role, action in role_privilege_changes:
        role_id = role["roleid"]
        try:
            post(
                f"roles({role_id})/Microsoft.Dynamics.CRM.AddPrivilegesRole",
                {
                    "Privileges": [
                        {
                            "Depth": str(TARGET_DEPTH),
                            "Name": "prvWriteContact",
                        }
                    ]
                },
            )
            print(f"  + {role['name']}: prvWriteContact set to BusinessUnit")
        except RuntimeError as e:
            print(f"  ! {role['name']}: {e}")
            errors += 1
        time.sleep(0.3)
    print()

# 5b. Create Field Security Profile if needed
if fls_active:
    if profile_action == "create":
        print(f"Creating Field Security Profile '{PROFILE_NAME}'...")
        try:
            resp = post(
                "fieldsecurityprofiles",
                {
                    "name": PROFILE_NAME,
                    "description": (
                        "Allows Sales Rep users to read and edit email address "
                        "fields (emailaddress1, emailaddress2) on Contact records."
                    ),
                },
            )
            location = resp.headers.get("OData-EntityId", "")
            # Extract GUID from URL like .../fieldsecurityprofiles(guid)
            profile_id = location.rstrip(")").rsplit("(", 1)[-1]
            print(f"  + Created: {profile_id}")
        except RuntimeError as e:
            print(f"  ! Could not create profile: {e}")
            errors += 1
            profile_id = None
        time.sleep(0.3)
        print()

    # 5c. Create/update field permissions within the profile
    if profile_id:
        print(f"Setting field permissions for '{PROFILE_NAME}'...")

        # Index existing permissions by field name for this profile
        existing_by_field = {}
        for fp in existing_fls:
            raw_pid = fp.get("_fieldsecurityprofileid_value") or fp.get("fieldsecurityprofileid")
            if str(raw_pid) == str(profile_id):
                existing_by_field[fp["attributelogicalname"]] = fp["fieldpermissionid"]

        for field in EMAIL_FIELDS:
            perm_body = {
                "canread": True,
                "cancreate": True,
                "canupdate": True,
            }
            try:
                if field in existing_by_field:
                    patch(f"fieldpermissions({existing_by_field[field]})", perm_body)
                    print(f"  ~ Updated: contact.{field}")
                else:
                    perm_body["entityname"] = "contact"
                    perm_body["attributelogicalname"] = field
                    perm_body["fieldsecurityprofileid@odata.bind"] = (
                        f"/fieldsecurityprofiles({profile_id})"
                    )
                    post("fieldpermissions", perm_body)
                    print(f"  + Created: contact.{field}")
            except RuntimeError as e:
                print(f"  ! contact.{field}: {e}")
                errors += 1
            time.sleep(0.3)
        print()

        # 5d. Assign profile to all Sales Rep users
        if sales_rep_users:
            print(f"Assigning '{PROFILE_NAME}' to Sales Rep users...")

            # Check which users already have this profile
            try:
                already_assigned = get(
                    f"fieldsecurityprofiles({profile_id})/systemuserprofiles_association",
                    {"$select": "systemuserid"},
                )
                already_ids = {u["systemuserid"] for u in already_assigned.get("value", [])}
            except RuntimeError:
                already_ids = set()

            for u in sales_rep_users:
                uid = u["systemuserid"]
                if uid in already_ids:
                    print(f"  = {u['fullname']}: already assigned")
                    continue
                try:
                    post(
                        f"fieldsecurityprofiles({profile_id})/systemuserprofiles_association/$ref",
                        {"@odata.id": f"{DYNAMICS_URL}/api/data/v9.2/systemusers({uid})"},
                    )
                    print(f"  + {u['fullname']}")
                except RuntimeError as e:
                    print(f"  ! {u['fullname']}: {e}")
                    errors += 1
                time.sleep(0.3)
            print()

print("Done.")
if errors:
    print(f"  Errors: {errors} — review output above for details.")
else:
    print("  All changes applied successfully.")
