# ============================================================
# crm_connection.py
# ============================================================
# This file handles logging into Microsoft Dynamics 365.
# Think of it like signing into your CRM account, but
# automatically, so Claude can access it.
#
# You don't need to change anything in here —
# it reads your credentials from the .env file.
# ============================================================

import os
import requests
from msal import ConfidentialClientApplication
from dotenv import load_dotenv

# Load credentials from the .env file
load_dotenv()

# Read the credentials we need
DYNAMICS_URL   = os.getenv("DYNAMICS_URL", "").rstrip("/")
TENANT_ID      = os.getenv("AZURE_TENANT_ID")
CLIENT_ID      = os.getenv("AZURE_CLIENT_ID")
CLIENT_SECRET  = os.getenv("AZURE_CLIENT_SECRET")


def get_access_token() -> str:
    """
    Logs into Microsoft and gets a temporary access token.
    This token is like a session key — it lets Claude talk to your CRM.
    Tokens expire after ~1 hour; this function always gets a fresh one.
    """
    if not all([TENANT_ID, CLIENT_ID, CLIENT_SECRET, DYNAMICS_URL]):
        raise ValueError(
            "Missing credentials. Please fill in all values in your .env file. "
            "See SETUP_GUIDE.md for instructions."
        )

    # Use Microsoft's authentication library (msal) to log in
    app = ConfidentialClientApplication(
        client_id=CLIENT_ID,
        client_credential=CLIENT_SECRET,
        authority=f"https://login.microsoftonline.com/{TENANT_ID}",
    )

    # Request an access token
    result = app.acquire_token_for_client(
        scopes=[f"{DYNAMICS_URL}/.default"]
    )

    if "access_token" not in result:
        error = result.get("error_description", "Unknown error")
        raise ConnectionError(
            f"Could not log into Microsoft CRM.\n"
            f"Error: {error}\n"
            f"Check your credentials in the .env file."
        )

    return result["access_token"]


def crm_get(endpoint: str, params: dict = None) -> dict:
    """
    Reads data from your CRM.

    endpoint: the type of data to fetch (e.g. "contacts", "leads")
    params:   optional filters (e.g. only active records)

    Returns the data as a Python dictionary.
    """
    token = get_access_token()

    url = f"{DYNAMICS_URL}/api/data/v9.2/{endpoint}"

    headers = {
        "Authorization": f"Bearer {token}",
        "OData-MaxVersion": "4.0",
        "OData-Version": "4.0",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Prefer": "odata.include-annotations=*",
    }

    response = requests.get(url, headers=headers, params=params)

    if not response.ok:
        raise RuntimeError(
            f"CRM read failed ({response.status_code}): {response.text[:500]}"
        )

    return response.json()


def crm_post(endpoint: str, data: dict) -> dict:
    """
    Creates a new record in your CRM.

    endpoint: the type of record (e.g. "contacts", "workflows")
    data:     the field values for the new record

    Returns the newly created record.
    """
    token = get_access_token()

    url = f"{DYNAMICS_URL}/api/data/v9.2/{endpoint}"

    headers = {
        "Authorization": f"Bearer {token}",
        "OData-MaxVersion": "4.0",
        "OData-Version": "4.0",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    response = requests.post(url, headers=headers, json=data)

    if not response.ok:
        raise RuntimeError(
            f"CRM create failed ({response.status_code}): {response.text[:500]}"
        )

    # Return the ID of the newly created record
    record_id = response.headers.get("OData-EntityId", "")
    return {"created": True, "record_url": record_id}


def crm_patch(endpoint: str, record_id: str, data: dict) -> dict:
    """
    Updates an existing record in your CRM.

    endpoint:  the type of record (e.g. "contacts")
    record_id: the unique ID of the record to update
    data:      the fields to change and their new values

    Returns a success confirmation.
    """
    token = get_access_token()

    url = f"{DYNAMICS_URL}/api/data/v9.2/{endpoint}({record_id})"

    headers = {
        "Authorization": f"Bearer {token}",
        "OData-MaxVersion": "4.0",
        "OData-Version": "4.0",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "If-Match": "*",
    }

    response = requests.patch(url, headers=headers, json=data)

    if not response.ok:
        raise RuntimeError(
            f"CRM update failed ({response.status_code}): {response.text[:500]}"
        )

    return {"updated": True, "record_id": record_id}


def crm_action(action_name: str, data: dict = None) -> dict:
    """
    Call an unbound Dynamics 365 Web API action (e.g. PublishXml).

    action_name: e.g. "PublishXml"
    data:        request body as a dict (can be empty)

    Returns the JSON response body, or {"success": True} for 204 responses.
    """
    token = get_access_token()

    url = f"{DYNAMICS_URL}/api/data/v9.2/{action_name}"

    headers = {
        "Authorization": f"Bearer {token}",
        "OData-MaxVersion": "4.0",
        "OData-Version": "4.0",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    response = requests.post(url, headers=headers, json=data or {})

    if not response.ok:
        raise RuntimeError(
            f"CRM action '{action_name}' failed ({response.status_code}): {response.text[:500]}"
        )

    if response.status_code == 204 or not response.content:
        return {"success": True}

    return response.json()


def crm_delete(endpoint: str, record_id: str) -> dict:
    """
    Deletes a record from your CRM.
    WARNING: This is permanent. Claude will only do this when explicitly told to.

    endpoint:  the type of record (e.g. "contacts")
    record_id: the unique ID of the record to delete
    """
    token = get_access_token()

    url = f"{DYNAMICS_URL}/api/data/v9.2/{endpoint}({record_id})"

    headers = {
        "Authorization": f"Bearer {token}",
        "OData-MaxVersion": "4.0",
        "OData-Version": "4.0",
    }

    response = requests.delete(url, headers=headers)

    if not response.ok:
        raise RuntimeError(
            f"CRM delete failed ({response.status_code}): {response.text[:500]}"
        )

    return {"deleted": True, "record_id": record_id}


def test_connection() -> dict:
    """
    Tests whether Claude can connect to your CRM.
    Run this first to make sure everything is set up correctly.
    """
    try:
        result = crm_get("WhoAmI")
        return {
            "connected": True,
            "message": "Successfully connected to Microsoft Dynamics 365",
            "user_id": result.get("UserId"),
        }
    except Exception as e:
        return {
            "connected": False,
            "message": str(e),
        }
