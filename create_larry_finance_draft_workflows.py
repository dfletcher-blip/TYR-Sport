"""
EXPERIMENTAL — create DRAFT classic Dynamics Workflows that route Larry
Meltzer's Lead and Special Terms submissions to the Finance team.

*** READ THIS FIRST ***
Classic Dynamics Workflow XAML embeds assembly version/token identifiers
and step-condition serialization specific to your org's exact Dynamics
build. This script is a genuine best-effort reconstruction, written
without live access to test against your tenant. The workflow shell
(name, entity, trigger settings) is solid — it POSTs with the same field
set already proven to work in this repo's clone_workflow tool. The inner
Check-Condition + Assign step XAML is the highest-risk part and may be
rejected outright, or may save but not behave as intended.

Safeguards built in:
  - Workflows are created in DRAFT only (statecode=0, statuscode=1).
  - This script NEVER activates them, with or without --dry-run.
    Nothing fires until a human opens each workflow in
    Settings > Processes, reviews the steps in the designer, and
    manually clicks Activate.
  - If Dynamics rejects the XAML outright, nothing is created — it
    fails loudly with the exact server error text so it can be fixed
    (same iterate-on-the-real-error approach used to fix the OData
    issues in the other scripts in this repo).
  - Before generating XAML, it searches this org for an existing
    classic Workflow (category 0) to source the real
    Microsoft.Crm.ObjectModel assembly version/token from — guessing
    that value wrong is the most common cause of "could not load type"
    errors. If this org has none, it falls back to a CRM-2011-era
    default and says so, which further raises the risk of rejection.

If this fails and you'd rather not debug legacy WF XAML by hand, build
the same two workflows in the classic Workflow designer instead — ask
for the step-by-step spec (entity, trigger, condition, action) already
provided separately.

Usage:
    python create_larry_finance_draft_workflows.py --dry-run   # preview
    python create_larry_finance_draft_workflows.py             # create as Draft
"""
import sys, os, re, uuid, time, requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv
load_dotenv()
from config.crm_connection import get_access_token

DYNAMICS_URL = os.getenv("DYNAMICS_URL", "").rstrip("/")
DRY_RUN = "--dry-run" in sys.argv

TARGET_NAME = "Larry Meltzer"
FINANCE_NAME_FILTER = "Finance"

DEFAULT_ASSEMBLY_VERSION = "5.0.0.0"
DEFAULT_PUBLIC_KEY_TOKEN = "31bf3856ad364e35"

_session = requests.Session()
_retry = Retry(total=4, backoff_factor=3,
               status_forcelist=[429, 500, 502, 503, 504],
               allowed_methods=["GET", "POST", "PATCH"])
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

def post(path, body):
    r = _session.post(f"{DYNAMICS_URL}/api/data/v9.2/{path}",
                      headers=get_headers(), json=body, timeout=30)
    if not r.ok:
        raise RuntimeError(f"POST {path} failed {r.status_code}: {r.text[:1000]}")
    return r

def find_user(full_name):
    first, *rest = full_name.strip().split()
    last = " ".join(rest)
    data = get("systemusers", {
        "$select": "systemuserid,fullname,internalemailaddress,isdisabled",
        "$filter": f"firstname eq '{first}' and lastname eq '{last}'",
    })
    users = [u for u in data.get("value", []) if not u.get("isdisabled")]
    if not users:
        data2 = get("systemusers", {
            "$select": "systemuserid,fullname,internalemailaddress,isdisabled",
            "$filter": f"contains(fullname,'{full_name}')",
        })
        users = [u for u in data2.get("value", []) if not u.get("isdisabled")]
    return users

def find_str_entity_logical_name():
    """Same metadata approach as setup_larry_finance_approval_routing.py."""
    try:
        meta = get("EntityDefinitions", {
            "$select": "LogicalName,LogicalCollectionName,DisplayName",
            "$filter": "IsCustomEntity eq true",
        })
        for e in meta.get("value", []):
            label = ((e.get("DisplayName") or {}).get("UserLocalizedLabel") or {}).get("Label", "")
            if "special term" in label.lower():
                return e.get("LogicalName", "")
    except RuntimeError as e:
        print(f"  (entity metadata lookup failed: {e})")
    return None

def get_donor_assembly_info():
    """
    Look for ANY classic Workflow (category 0) anywhere in this org and
    reuse the exact Microsoft.Crm.ObjectModel assembly version/token it
    references, since that must match this org's installed build.
    Falls back to a CRM-2011-era default if none exist to borrow from.
    """
    try:
        data = get("workflows", {
            "$select": "workflowid,name,xaml,category",
            "$filter": "category eq 0",
            "$top": 10,
        })
    except RuntimeError as e:
        print(f"  (donor workflow search failed: {e})")
        data = {"value": []}

    for wf in data.get("value", []):
        xaml = wf.get("xaml") or ""
        m = re.search(
            r"Microsoft\.Crm\.ObjectModel,\s*Version=([\d.]+),\s*Culture=neutral,\s*PublicKeyToken=([0-9a-fA-F]+)",
            xaml,
        )
        if m:
            print(f"  Sourced assembly version {m.group(1)} from existing workflow '{wf.get('name')}'.")
            return m.group(1), m.group(2)

    print("  WARNING: No classic Workflow objects exist anywhere in this org to")
    print("  source a known-good assembly version from. Falling back to a")
    print(f"  best-guess default ({DEFAULT_ASSEMBLY_VERSION}) — this significantly")
    print("  raises the chance Dynamics rejects the XAML below.")
    return DEFAULT_ASSEMBLY_VERSION, DEFAULT_PUBLIC_KEY_TOKEN


def build_condition_assign_xaml(asm_version, asm_token, condition_value_guid, assign_team_guid):
    """
    Best-effort classic-Workflow XAML: IF Created By equals
    {condition_value_guid} THEN assign the record to team
    {assign_team_guid}. EXPERIMENTAL — see module docstring. This is the
    single highest-risk part of this script.
    """
    wf_guid = uuid.uuid4().hex.upper()
    cond_name = f"Condition{uuid.uuid4().hex[:8].upper()}"

    return f"""<?xml version="1.0" encoding="utf-16"?>
<Activity x:Class="Microsoft.Crm.Workflow.Wf{wf_guid}"
    x:Name="Wf{wf_guid}"
    xmlns:mxswa="http://schemas.microsoft.com/crm/2006/WWF"
    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
    xmlns:mxsw="clr-namespace:Microsoft.Crm.Workflow;assembly=Microsoft.Crm.Workflow, Version={asm_version}, Culture=neutral, PublicKeyToken={asm_token}"
    xmlns:this="clr-namespace:Microsoft.Crm.Workflow">
  <mxswa:ActivityLibraryReference AssemblyName="Microsoft.Crm.ObjectModel, Version={asm_version}, Culture=neutral, PublicKeyToken={asm_token}">
    <mxswa:ActivityLibraryReference.Types>
      <mxswa:ActivityLibraryType Name="Microsoft.Crm.ObjectModel.CheckConditionStepActivity" />
      <mxswa:ActivityLibraryType Name="Microsoft.Crm.ObjectModel.AssignActivity" />
    </mxswa:ActivityLibraryReference.Types>
  </mxswa:ActivityLibraryReference>
  <mxsw:Workflow.Rules>
    <RuleDefinitions xmlns="clr-namespace:System.Workflow.Activities.Rules;assembly=System.Workflow.Activities, Version=4.0.0.0, Culture=neutral, PublicKeyToken=31bf3856ad364e35">
      <RuleDefinitions.Conditions>
        <RuleExpressionCondition Name="{cond_name}">
          <RuleExpressionCondition.Expression>
            <mxswa:CrmExpression ExpressionText="this.GetAttributeValue(&quot;createdby&quot;) == new global::System.Guid(&quot;{condition_value_guid}&quot;)" />
          </RuleExpressionCondition.Expression>
        </RuleExpressionCondition>
      </RuleDefinitions.Conditions>
    </RuleDefinitions>
  </mxsw:Workflow.Rules>
  <Sequence.Activities>
    <this:CheckConditionStepActivity x:Name="CheckCondition1" Condition="{{x:Reference {cond_name}}}">
      <this:CheckConditionStepActivity.WhenTrue>
        <Sequence.Activities>
          <this:AssignActivity x:Name="Assign1" Assignee="{{x:Static Guid.Parse(&quot;{assign_team_guid}&quot;)}}" />
        </Sequence.Activities>
      </this:CheckConditionStepActivity.WhenTrue>
    </this:CheckConditionStepActivity>
  </Sequence.Activities>
</Activity>"""


def create_draft_workflow(name, entity, xaml):
    """
    Create a new classic Workflow as a Draft. Uses the same field set as
    the existing clone_workflow tool (tools/workflows.py), which is
    proven to work against this exact org — only the xaml content itself
    is new/unverified.
    """
    payload = {
        "name": name,
        "description": f"EXPERIMENTAL — routes {TARGET_NAME}'s submissions to Finance for approval. Review in the designer before activating.",
        "category": 0,
        "primaryentity": entity,
        "xaml": xaml,
        "triggeroncreate": True,
    }
    r = post("workflows", payload)
    record_id = r.headers.get("OData-EntityId", "")
    return record_id


# ── Look up Larry, Finance team, and the STR entity ─────────────────────────
print("Looking up user...")
matches = find_user(TARGET_NAME)
if not matches:
    print(f"ERROR: '{TARGET_NAME}' not found")
    sys.exit(1)
larry = matches[0]
larry_id = larry["systemuserid"]
print(f"  {larry['fullname']} — {larry_id}")
print()

print(f"Looking up team matching '{FINANCE_NAME_FILTER}'...")
finance_teams = get("teams", {
    "$select": "teamid,name",
    "$filter": f"contains(name,'{FINANCE_NAME_FILTER}')",
}).get("value", [])
if not finance_teams:
    print(f"ERROR: No team found matching '{FINANCE_NAME_FILTER}'.")
    sys.exit(1)
finance_team = finance_teams[0]
print(f"  {finance_team['name']} — {finance_team['teamid']}")
print()

str_logical = find_str_entity_logical_name()
if not str_logical:
    print("ERROR: Could not discover the Special Terms entity logical name.")
    sys.exit(1)
print(f"Special Terms entity logical name: '{str_logical}'")
print()

print("Looking for a donor classic Workflow to source assembly info from...")
asm_version, asm_token = get_donor_assembly_info()
print()

if DRY_RUN:
    print("*** DRY RUN — no workflows will be created ***\n")

workflows_to_create = [
    ("Route Larry Meltzer's Lead Submissions to Finance", "lead"),
    ("Route Larry Meltzer's Special Terms Submissions to Finance", str_logical),
]

for name, entity in workflows_to_create:
    print(f"{'Would create' if DRY_RUN else 'Creating'}: '{name}' on entity '{entity}'")

if DRY_RUN:
    print("\nDry run complete. Run without --dry-run to create these as Draft workflows.")
    print("They will NOT be activated automatically — that step is manual, in the")
    print("Dynamics Workflow designer, after you've reviewed the steps.")
    sys.exit(0)

print()
created = errors = 0
for name, entity in workflows_to_create:
    try:
        xaml = build_condition_assign_xaml(asm_version, asm_token, larry_id, finance_team["teamid"])
        record_id = create_draft_workflow(name, entity, xaml)
        print(f"  + Created (Draft): {name}")
        print(f"    {record_id}")
        created += 1
    except RuntimeError as e:
        print(f"  ! FAILED: {name}")
        print(f"    {e}")
        errors += 1
    print()

print("Done.")
print(f"  Created: {created}")
print(f"  Failed : {errors}")
if created:
    print()
    print("IMPORTANT: These are Draft only and will NOT fire yet. Open each one in")
    print("Settings > Processes in Dynamics, review the Check Condition / Assign")
    print("steps in the designer, and manually Activate only once they look correct.")
if errors:
    print()
    print("If workflow creation failed, paste the exact error text back for a fix —")
    print("the XAML content (build_condition_assign_xaml) is the part most likely")
    print("to need correction based on what Dynamics actually reports.")
