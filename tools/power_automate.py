# ============================================================
# tools/power_automate.py — Power Automate Flow Management
# ============================================================
# Lets the agent create, list, and manage Power Automate flows
# that react to Dynamics 365 events in real time.
# ============================================================

import os, sys, uuid, time, requests
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from msal import ConfidentialClientApplication
from dotenv import load_dotenv
load_dotenv()

TENANT_ID     = os.getenv("AZURE_TENANT_ID")
CLIENT_ID     = os.getenv("AZURE_CLIENT_ID")
CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET")
DYNAMICS_URL  = os.getenv("DYNAMICS_URL", "").rstrip("/")

# Power Automate API base
PA_API = "https://api.flow.microsoft.com"

_pa_token = {"value": None, "expires": 0}
_crm_token = {"value": None, "expires": 0}


def _get_pa_token() -> str:
    if not _pa_token["value"] or time.time() >= _pa_token["expires"]:
        app = ConfidentialClientApplication(
            client_id=CLIENT_ID,
            client_credential=CLIENT_SECRET,
            authority=f"https://login.microsoftonline.com/{TENANT_ID}",
        )
        result = app.acquire_token_for_client(
            scopes=["https://service.flow.microsoft.com/.default"]
        )
        if "access_token" not in result:
            raise ConnectionError(f"Power Automate auth failed: {result.get('error_description')}")
        _pa_token["value"]   = result["access_token"]
        _pa_token["expires"] = time.time() + 3000
    return _pa_token["value"]


def _get_crm_token() -> str:
    if not _crm_token["value"] or time.time() >= _crm_token["expires"]:
        app = ConfidentialClientApplication(
            client_id=CLIENT_ID,
            client_credential=CLIENT_SECRET,
            authority=f"https://login.microsoftonline.com/{TENANT_ID}",
        )
        result = app.acquire_token_for_client(scopes=[f"{DYNAMICS_URL}/.default"])
        if "access_token" not in result:
            raise ConnectionError(f"CRM auth failed: {result.get('error_description')}")
        _crm_token["value"]   = result["access_token"]
        _crm_token["expires"] = time.time() + 3000
    return _crm_token["value"]


def _pa_headers():
    return {
        "Authorization": f"Bearer {_get_pa_token()}",
        "Content-Type":  "application/json",
        "Accept":        "application/json",
    }


def _get_environment_id() -> str:
    """Resolve the default Power Automate environment for this tenant."""
    r = requests.get(
        f"{PA_API}/providers/Microsoft.ProcessSimple/environments",
        headers=_pa_headers(),
        params={"api-version": "2016-11-01"},
        timeout=30,
    )
    r.raise_for_status()
    envs = r.json().get("value", [])
    # Prefer the default environment
    default = next((e for e in envs if e.get("properties", {}).get("isDefault")), None)
    env = default or (envs[0] if envs else None)
    if not env:
        raise RuntimeError("No Power Automate environments found for this tenant.")
    return env["name"]


def _get_dataverse_connection_name(env_id: str) -> str:
    """Find an existing Dataverse (CDS) connection in the environment."""
    r = requests.get(
        f"{PA_API}/providers/Microsoft.ProcessSimple/environments/{env_id}/connections",
        headers=_pa_headers(),
        params={"api-version": "2016-11-01"},
        timeout=30,
    )
    r.raise_for_status()
    connections = r.json().get("value", [])
    # Look for a Dataverse / Common Data Service connection
    for c in connections:
        api_id = c.get("properties", {}).get("apiId", "").lower()
        if "commondataserviceforapps" in api_id or "dataverse" in api_id:
            return c["name"]
    return None


def list_flows() -> dict:
    """
    List all Power Automate flows in this environment.
    """
    try:
        env_id = _get_environment_id()
        r = requests.get(
            f"{PA_API}/providers/Microsoft.ProcessSimple/environments/{env_id}/flows",
            headers=_pa_headers(),
            params={"api-version": "2016-11-01", "$top": 100},
            timeout=30,
        )
        r.raise_for_status()
        flows = r.json().get("value", [])
        return {
            "environment": env_id,
            "total": len(flows),
            "flows": [
                {
                    "id":          f["name"],
                    "display_name": f.get("properties", {}).get("displayName", ""),
                    "state":       f.get("properties", {}).get("state", ""),
                    "created":     f.get("properties", {}).get("createdTime", ""),
                }
                for f in flows
            ],
        }
    except Exception as e:
        return {"error": str(e)}


def create_lead_status_flow(
    trigger_table: str,
    trigger_description: str,
    status_field: str,
    status_value: int,
    flow_name: str,
    direction_filter: str = None,
) -> dict:
    """
    Create a Power Automate flow that updates a lead's status field
    when a new row is added to trigger_table.

    trigger_table:       Dataverse table that triggers the flow
                         e.g. "activitypointers" or "emails"
    trigger_description: human-readable description of the trigger
    status_field:        field on the lead to update e.g. "statuscode"
    status_value:        integer value to set
    flow_name:           display name for the flow
    direction_filter:    optional — "Incoming" to filter inbound emails only
    """
    try:
        env_id      = _get_environment_id()
        conn_name   = _get_dataverse_connection_name(env_id)

        if not conn_name:
            return {
                "success": False,
                "error":   (
                    "No Dataverse connection found in Power Automate. "
                    "Go to make.powerautomate.com → Data → Connections → New connection → "
                    "Microsoft Dataverse, then re-run."
                ),
            }

        conn_ref_key = "shared_commondataserviceforapps"
        api_id       = f"/providers/Microsoft.PowerApps/apis/{conn_ref_key}"

        # ── Build trigger ──────────────────────────────────────────────────────
        trigger_def = {
            "type": "OpenApiConnectionWebhook",
            "inputs": {
                "host": {
                    "connectionName": conn_ref_key,
                    "operationId":    "SubscribeWebhookTrigger",
                    "apiId":          api_id,
                },
                "parameters": {
                    "subscriptionRequest/message":    1,   # Create
                    "subscriptionRequest/entityname": trigger_table,
                    "subscriptionRequest/scope":      4,   # Organization
                },
                "authentication": "@parameters('$authentication')",
            },
        }

        # ── Build actions ──────────────────────────────────────────────────────
        actions = {}

        # Optional direction filter (inbound email only)
        update_run_after = {}
        if direction_filter == "Incoming":
            actions["Check_Incoming"] = {
                "type": "If",
                "expression": {
                    "and": [
                        {"equals": ["@triggerOutputs()?['body/directioncode']", True]}
                    ]
                },
                "actions": {
                    "Update_Lead_Status": {
                        "type": "OpenApiConnection",
                        "inputs": {
                            "host": {
                                "connectionName": conn_ref_key,
                                "operationId":    "UpdateRecord",
                                "apiId":          api_id,
                            },
                            "parameters": {
                                "entityName": "leads",
                                "recordId":   "@triggerOutputs()?['body/_regardingobjectid_value']",
                                f"item/{status_field}": status_value,
                            },
                            "authentication": "@parameters('$authentication')",
                        },
                    }
                },
                "else": {"actions": {}},
            }
        else:
            actions["Update_Lead_Status"] = {
                "type": "OpenApiConnection",
                "inputs": {
                    "host": {
                        "connectionName": conn_ref_key,
                        "operationId":    "UpdateRecord",
                        "apiId":          api_id,
                    },
                    "parameters": {
                        "entityName": "leads",
                        "recordId":   "@triggerOutputs()?['body/_regardingobjectid_value']",
                        f"item/{status_field}": status_value,
                    },
                    "authentication": "@parameters('$authentication')",
                },
            }

        # ── Full flow definition ───────────────────────────────────────────────
        flow_def = {
            "properties": {
                "displayName": flow_name,
                "state":       "Started",
                "definition": {
                    "$schema":     "https://schema.management.azure.com/providers/Microsoft.Logic/schemas/2016-06-01/workflowdefinition.json#",
                    "contentVersion": "1.0.0.0",
                    "parameters": {
                        "$connections": {"defaultValue": {}, "type": "Object"},
                        "$authentication": {"defaultValue": {}, "type": "SecureObject"},
                    },
                    "triggers":  {"When_a_row_is_added": trigger_def},
                    "actions":   actions,
                },
                "connectionReferences": {
                    conn_ref_key: {
                        "runtimeSource": "embedded",
                        "connection":    {"name": f"/providers/Microsoft.PowerApps/apis/{conn_ref_key}/connections/{conn_name}"},
                        "api":           {"name": conn_ref_key},
                    }
                },
            }
        }

        r = requests.post(
            f"{PA_API}/providers/Microsoft.ProcessSimple/environments/{env_id}/flows",
            headers=_pa_headers(),
            params={"api-version": "2016-11-01"},
            json=flow_def,
            timeout=30,
        )

        if r.status_code in (200, 201):
            flow_id = r.json().get("name", "")
            return {
                "success":      True,
                "flow_id":      flow_id,
                "flow_name":    flow_name,
                "trigger":      trigger_description,
                "sets_field":   status_field,
                "sets_value":   status_value,
                "message":      f"Flow '{flow_name}' created and started.",
            }
        else:
            return {
                "success": False,
                "error":   f"{r.status_code}: {r.text[:400]}",
                "hint":    (
                    "If this is a permissions error, ensure the Azure app registration has "
                    "the 'Flows.ReadWrite.All' API permission under Power Automate (service.flow.microsoft.com)."
                ),
            }

    except Exception as e:
        return {"success": False, "error": str(e)}


def create_lead_stage_flows(
    contacting_status_value: int,
    engaged_status_value: int,
) -> dict:
    """
    Create both lead stage automation flows in one call:
      1. Activity logged on a lead  → set statuscode to Contacting
      2. Inbound email from a lead  → set statuscode to Engaged

    contacting_status_value: integer statuscode for Contacting (e.g. 2)
    engaged_status_value:    integer statuscode for Engaged (e.g. 935650001)
    """
    results = {}

    results["activity_to_contacting"] = create_lead_status_flow(
        trigger_table=       "activitypointers",
        trigger_description= "Any activity (call, email, task) created regarding a lead",
        status_field=        "statuscode",
        status_value=        contacting_status_value,
        flow_name=           "TYR - Lead: Activity Logged → Contacting",
    )

    results["email_reply_to_engaged"] = create_lead_status_flow(
        trigger_table=       "emails",
        trigger_description= "Inbound email received regarding a lead",
        status_field=        "statuscode",
        status_value=        engaged_status_value,
        flow_name=           "TYR - Lead: Email Reply Received → Engaged",
        direction_filter=    "Incoming",
    )

    both_ok = all(v.get("success") for v in results.values())
    return {
        "success": both_ok,
        "flows":   results,
        "message": "Both flows created." if both_ok else "One or more flows failed — see details.",
    }
