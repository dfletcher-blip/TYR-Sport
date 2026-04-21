# ============================================================
# tools/acs_api.py — ACS ERP API Adapter
# ============================================================
# Fetches the WIP receive report from the ACS ERP system.
#
# CONFIGURATION (.env variables):
#   ACS_BASE_URL    — Base URL of the ACS API (e.g. https://acs.yourcompany.com)
#   ACS_API_KEY     — API key for Bearer token auth (preferred)
#   ACS_USERNAME    — Username if ACS uses basic auth instead
#   ACS_PASSWORD    — Password if ACS uses basic auth instead
#   ACS_MOCK_DATA   — Set to "true" to use built-in mock data (no ACS connection needed)
#
# GETTING CREDENTIALS:
#   Contact your ACS system administrator to obtain API access.
#   Until then, set ACS_MOCK_DATA=true in your .env file to test with sample data.
# ============================================================

import os
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()


# ── Mock data ─────────────────────────────────────────────────────────────────
# Used when ACS_MOCK_DATA=true or no ACS_BASE_URL is configured.
# These records represent a realistic WIP receive report snapshot, including
# open POs, a partially received shipment, and one fully received item.

def _mock_wip_report() -> list[dict]:
    today = datetime.now()
    return [
        {
            "po_number": "PO-2025-0042",
            "line_number": 1,
            "sku": "SWIM-M-BLU-MD",
            "description": "Men's Swim Jammer - Blue - Medium",
            "quantity_ordered": 200,
            "quantity_received": 0,
            "expected_delivery_date": (today + timedelta(days=10)).strftime("%Y-%m-%d"),
            "actual_receipt_date": None,
            "status": "Open",
            "vendor": "Pacific Sportswear",
            "buyer": "Sarah Johnson",
            "category": "Swimwear",
        },
        {
            "po_number": "PO-2025-0042",
            "line_number": 2,
            "sku": "SWIM-M-BLU-LG",
            "description": "Men's Swim Jammer - Blue - Large",
            "quantity_ordered": 150,
            "quantity_received": 0,
            "expected_delivery_date": (today + timedelta(days=10)).strftime("%Y-%m-%d"),
            "actual_receipt_date": None,
            "status": "Open",
            "vendor": "Pacific Sportswear",
            "buyer": "Sarah Johnson",
            "category": "Swimwear",
        },
        {
            "po_number": "PO-2025-0055",
            "line_number": 1,
            "sku": "SUIT-W-RED-SM",
            "description": "Women's Competition Suit - Red - Small",
            "quantity_ordered": 100,
            "quantity_received": 45,
            "expected_delivery_date": (today + timedelta(days=3)).strftime("%Y-%m-%d"),
            "actual_receipt_date": None,
            "status": "Partially Received",
            "vendor": "Elite Aquatics Mfg",
            "buyer": "Mark Torres",
            "category": "Swimwear",
        },
        {
            "po_number": "PO-2025-0055",
            "line_number": 2,
            "sku": "SUIT-W-RED-MD",
            "description": "Women's Competition Suit - Red - Medium",
            "quantity_ordered": 120,
            "quantity_received": 0,
            "expected_delivery_date": (today + timedelta(days=3)).strftime("%Y-%m-%d"),
            "actual_receipt_date": None,
            "status": "Open",
            "vendor": "Elite Aquatics Mfg",
            "buyer": "Mark Torres",
            "category": "Swimwear",
        },
        {
            "po_number": "PO-2025-0061",
            "line_number": 1,
            "sku": "GOGGLE-ELITE-CLR",
            "description": "Elite Racing Goggles - Clear Lens",
            "quantity_ordered": 500,
            "quantity_received": 500,
            "expected_delivery_date": (today - timedelta(days=2)).strftime("%Y-%m-%d"),
            "actual_receipt_date": today.strftime("%Y-%m-%d"),
            "status": "Received",
            "vendor": "TechVision Eyewear",
            "buyer": "Sarah Johnson",
            "category": "Accessories",
        },
        {
            "po_number": "PO-2025-0063",
            "line_number": 1,
            "sku": "CAP-SILICONE-BLK",
            "description": "Silicone Swim Cap - Black",
            "quantity_ordered": 1000,
            "quantity_received": 0,
            "expected_delivery_date": (today + timedelta(days=21)).strftime("%Y-%m-%d"),
            "actual_receipt_date": None,
            "status": "Open",
            "vendor": "Aqua Gear Co.",
            "buyer": "Mark Torres",
            "category": "Accessories",
        },
        {
            "po_number": "PO-2025-0067",
            "line_number": 1,
            "sku": "BRIEF-M-TYR-SM",
            "description": "Men's TYR Brief - Assorted - Small",
            "quantity_ordered": 300,
            "quantity_received": 0,
            "expected_delivery_date": (today + timedelta(days=14)).strftime("%Y-%m-%d"),
            "actual_receipt_date": None,
            "status": "Open",
            "vendor": "Pacific Sportswear",
            "buyer": "Sarah Johnson",
            "category": "Swimwear",
        },
        {
            "po_number": "PO-2025-0070",
            "line_number": 1,
            "sku": "BOARD-PULLKICK-STD",
            "description": "Pull Kick Training Board - Standard",
            "quantity_ordered": 250,
            "quantity_received": 0,
            "expected_delivery_date": (today + timedelta(days=7)).strftime("%Y-%m-%d"),
            "actual_receipt_date": None,
            "status": "Open",
            "vendor": "SwimTech Equipment",
            "buyer": "Mark Torres",
            "category": "Training Equipment",
        },
    ]


# ── ACS field normalization ────────────────────────────────────────────────────

def _normalize_acs_response(data: list | dict) -> list[dict]:
    """
    Map ACS API response fields to our standard WIP item schema.

    TODO: Update this mapping once you have the actual ACS API response format.
    The current mapping tries common field name conventions (snake_case,
    camelCase, abbreviations) to handle variations in the ACS response.
    """
    if isinstance(data, dict):
        # Some APIs wrap the list under a key like "items", "records", "data"
        for key in ("items", "records", "data", "results", "purchaseOrders"):
            if key in data:
                data = data[key]
                break

    if not isinstance(data, list):
        raise ValueError(
            f"Unexpected ACS response format: expected a list or dict with an "
            f"'items'/'records'/'data' key, got {type(data).__name__}. "
            "Update _normalize_acs_response() to match the actual ACS response structure."
        )

    normalized = []
    for item in data:
        normalized.append({
            "po_number": (
                item.get("po_number")
                or item.get("purchaseOrderNumber")
                or item.get("poNumber")
                or item.get("poNum")
                or item.get("PO_NUMBER", "")
            ),
            "line_number": int(
                item.get("line_number")
                or item.get("lineNumber")
                or item.get("lineNum")
                or item.get("LINE_NUMBER")
                or 0
            ),
            "sku": (
                item.get("sku")
                or item.get("itemNumber")
                or item.get("itemNum")
                or item.get("productCode")
                or item.get("SKU", "")
            ),
            "description": (
                item.get("description")
                or item.get("itemDescription")
                or item.get("productName")
                or item.get("DESCRIPTION", "")
            ),
            "quantity_ordered": float(
                item.get("quantity_ordered")
                or item.get("quantityOrdered")
                or item.get("qtyOrdered")
                or item.get("QTY_ORDERED")
                or 0
            ),
            "quantity_received": float(
                item.get("quantity_received")
                or item.get("quantityReceived")
                or item.get("qtyReceived")
                or item.get("QTY_RECEIVED")
                or 0
            ),
            "expected_delivery_date": (
                item.get("expected_delivery_date")
                or item.get("expectedDeliveryDate")
                or item.get("edd")
                or item.get("EDD")
                or item.get("expectedDate", "")
            ),
            "actual_receipt_date": (
                item.get("actual_receipt_date")
                or item.get("actualReceiptDate")
                or item.get("receivedDate")
                or item.get("dateReceived")
                or item.get("RECEIPT_DATE")
            ),
            "status": (
                item.get("status")
                or item.get("orderStatus")
                or item.get("lineStatus")
                or item.get("STATUS", "Unknown")
            ),
            "vendor": (
                item.get("vendor")
                or item.get("vendorName")
                or item.get("supplierName")
                or item.get("supplier")
                or item.get("VENDOR", "")
            ),
            "buyer": (
                item.get("buyer")
                or item.get("buyerName")
                or item.get("purchasingAgent")
                or item.get("BUYER", "")
            ),
            "category": (
                item.get("category")
                or item.get("productCategory")
                or item.get("department")
                or item.get("dept")
                or item.get("CATEGORY", "")
            ),
        })
    return normalized


# ── Public API ─────────────────────────────────────────────────────────────────

def fetch_wip_report() -> list[dict]:
    """
    Fetch the current WIP receive report from ACS.

    Returns a list of dicts, one per PO line, with these standard fields:
      po_number             — Purchase order number (e.g. "PO-2025-0042")
      line_number           — Line number within the PO (integer)
      sku                   — Product SKU / item number
      description           — Human-readable product description
      quantity_ordered      — Total quantity on this PO line
      quantity_received     — Quantity received to date
      expected_delivery_date — Expected arrival date (YYYY-MM-DD string)
      actual_receipt_date   — Date actually received (YYYY-MM-DD string or None)
      status                — Open / Partially Received / Received / Cancelled / On Hold
      vendor                — Supplier / vendor name
      buyer                 — Purchasing buyer name
      category              — Product category / department

    Raises RuntimeError if the API request fails.

    TO CONNECT TO THE REAL ACS API:
      1. Set ACS_BASE_URL in your .env file (e.g. https://acs.yourcompany.com)
      2. Set ACS_API_KEY (or ACS_USERNAME + ACS_PASSWORD) in your .env file
      3. Update the endpoint path below to match the actual ACS WIP report endpoint
      4. Run once and inspect the response; update _normalize_acs_response() if
         the ACS field names differ from the expected conventions above
    """
    mock_mode = os.getenv("ACS_MOCK_DATA", "").lower() in ("true", "1", "yes")
    base_url = os.getenv("ACS_BASE_URL", "").rstrip("/")

    if mock_mode or not base_url:
        print("[ACS] Running in mock mode — set ACS_BASE_URL in .env to connect to live ACS data")
        return _mock_wip_report()

    # TODO: Confirm the exact ACS endpoint path for the WIP receive report
    endpoint = f"{base_url}/api/v1/wip-receive-report"

    headers = {"Accept": "application/json"}

    api_key = os.getenv("ACS_API_KEY", "")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    # Fallback to basic auth if username/password provided instead of API key
    username = os.getenv("ACS_USERNAME", "")
    password = os.getenv("ACS_PASSWORD", "")
    auth = (username, password) if (username and not api_key) else None

    try:
        response = requests.get(endpoint, headers=headers, auth=auth, timeout=30)
        response.raise_for_status()
        return _normalize_acs_response(response.json())
    except requests.exceptions.Timeout:
        raise RuntimeError("ACS API timed out after 30s. Check ACS_BASE_URL and network connectivity.")
    except requests.exceptions.HTTPError as e:
        raise RuntimeError(
            f"ACS API returned HTTP {e.response.status_code}. "
            f"Response: {e.response.text[:300]}"
        )
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"ACS API connection error: {e}")
