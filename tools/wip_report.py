# ============================================================
# tools/wip_report.py — WIP Report Snapshot & Change Detection
# ============================================================
# Loads and saves a snapshot of the WIP receive report between
# agent runs, then diffs the current report against that snapshot
# to identify arrivals and expected-delivery-date changes.
# ============================================================

import json
import os
from datetime import datetime
from typing import Optional

SNAPSHOT_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "wip_snapshot.json")


# ── Unique key for a PO line ───────────────────────────────────────────────────

def _item_key(item: dict) -> str:
    """Stable unique identifier for a WIP line item across report runs."""
    return f"{item['po_number']}::{item['line_number']}::{item['sku']}"


# ── Snapshot persistence ───────────────────────────────────────────────────────

def load_wip_snapshot() -> dict:
    """
    Load the last saved WIP snapshot from disk.

    Returns a dict keyed by item key (PO::line::SKU), with each value being
    the full item dict from the previous run. Returns empty dict if no snapshot exists.
    """
    if not os.path.exists(SNAPSHOT_PATH):
        return {}
    try:
        with open(SNAPSHOT_PATH, "r") as f:
            data = json.load(f)
        return data.get("items", {})
    except (json.JSONDecodeError, KeyError):
        return {}


def save_wip_snapshot(items: list[dict]) -> None:
    """
    Save the current WIP report to disk as the new snapshot.
    Creates the data/ directory if it doesn't exist.
    """
    os.makedirs(os.path.dirname(SNAPSHOT_PATH), exist_ok=True)
    snapshot = {
        "saved_at": datetime.utcnow().isoformat() + "Z",
        "item_count": len(items),
        "items": {_item_key(item): item for item in items},
    }
    with open(SNAPSHOT_PATH, "w") as f:
        json.dump(snapshot, f, indent=2)


def get_snapshot_age() -> Optional[str]:
    """Return human-readable age of the last snapshot, or None if no snapshot exists."""
    if not os.path.exists(SNAPSHOT_PATH):
        return None
    try:
        with open(SNAPSHOT_PATH, "r") as f:
            data = json.load(f)
        saved_at = data.get("saved_at", "")
        if not saved_at:
            return None
        dt = datetime.fromisoformat(saved_at.rstrip("Z"))
        delta = datetime.utcnow() - dt
        hours = int(delta.total_seconds() // 3600)
        minutes = int((delta.total_seconds() % 3600) // 60)
        if hours >= 24:
            return f"{hours // 24}d {hours % 24}h ago"
        if hours > 0:
            return f"{hours}h {minutes}m ago"
        return f"{minutes}m ago"
    except Exception:
        return None


# ── Change detection ───────────────────────────────────────────────────────────

def detect_wip_changes(current_items: list[dict], previous_snapshot: dict) -> dict:
    """
    Compare the current WIP report against the previous snapshot and return
    a structured dict describing what changed.

    Returns:
      {
        "arrivals":        [...],   # Items newly fully received
        "partial_arrivals":[...],   # Items where qty_received increased (but not fully received)
        "date_changes":    [...],   # Items whose expected_delivery_date changed
        "new_items":       [...],   # Items not seen in the previous snapshot
        "cancellations":   [...],   # Items whose status changed to Cancelled / On Hold
        "total_changes":   int,
        "has_changes":     bool,
      }

    Each event dict contains the current item fields plus additional context:
      - For arrivals: also includes "previous_qty_received"
      - For partial_arrivals: also includes "previous_qty_received", "qty_increase"
      - For date_changes: also includes "previous_date", "days_shifted" (negative = earlier)
      - For cancellations: also includes "previous_status"
    """
    arrivals = []
    partial_arrivals = []
    date_changes = []
    new_items = []
    cancellations = []

    cancelled_statuses = {"cancelled", "canceled", "on hold", "voided", "void"}

    for item in current_items:
        key = _item_key(item)
        prev = previous_snapshot.get(key)

        if prev is None:
            # Brand new PO line — only noteworthy if it's already received or almost due
            new_items.append({**item, "event": "new_item"})
            continue

        current_status = (item.get("status") or "").strip().lower()
        previous_status = (prev.get("status") or "").strip().lower()

        # Check for cancellations / holds
        if current_status in cancelled_statuses and previous_status not in cancelled_statuses:
            cancellations.append({
                **item,
                "event": "cancellation",
                "previous_status": prev.get("status", ""),
            })
            continue  # No need to check other changes for a cancelled line

        # Check for full arrival
        qty_ordered = float(item.get("quantity_ordered") or 0)
        qty_received_now = float(item.get("quantity_received") or 0)
        qty_received_prev = float(prev.get("quantity_received") or 0)

        if qty_received_now >= qty_ordered > 0 and qty_received_prev < qty_ordered:
            arrivals.append({
                **item,
                "event": "arrival",
                "previous_qty_received": qty_received_prev,
            })
            continue  # A full arrival supersedes a partial arrival event

        # Check for partial arrival (qty increased but not complete)
        if qty_received_now > qty_received_prev:
            arrivals_pct = (qty_received_now / qty_ordered * 100) if qty_ordered > 0 else 0
            partial_arrivals.append({
                **item,
                "event": "partial_arrival",
                "previous_qty_received": qty_received_prev,
                "qty_increase": qty_received_now - qty_received_prev,
                "pct_received": round(arrivals_pct, 1),
            })

        # Check for expected delivery date change (independent of qty changes)
        current_edd = (item.get("expected_delivery_date") or "").strip()
        previous_edd = (prev.get("expected_delivery_date") or "").strip()

        if current_edd and previous_edd and current_edd != previous_edd:
            days_shifted = _date_diff_days(current_edd, previous_edd)
            date_changes.append({
                **item,
                "event": "date_change",
                "previous_date": previous_edd,
                "days_shifted": days_shifted,
                "direction": "earlier" if days_shifted < 0 else "later",
            })

    total = len(arrivals) + len(partial_arrivals) + len(date_changes) + len(cancellations)

    return {
        "arrivals": arrivals,
        "partial_arrivals": partial_arrivals,
        "date_changes": date_changes,
        "new_items": new_items,
        "cancellations": cancellations,
        "total_changes": total,
        "has_changes": total > 0,
        "checked_at": datetime.utcnow().isoformat() + "Z",
    }


def _date_diff_days(date_a: str, date_b: str) -> int:
    """Return (date_a - date_b) in days. Negative means date_a is earlier."""
    try:
        fmt = "%Y-%m-%d"
        return (datetime.strptime(date_a, fmt) - datetime.strptime(date_b, fmt)).days
    except ValueError:
        return 0


# ── Human-readable summary ─────────────────────────────────────────────────────

def format_change_summary(changes: dict) -> str:
    """
    Return a compact plain-text summary of detected changes suitable for
    printing to the terminal or including in a log.
    """
    if not changes["has_changes"]:
        return "No changes detected since last snapshot."

    lines = [f"WIP Report — {changes['total_changes']} change(s) detected"]
    lines.append(f"Checked at: {changes['checked_at']}")
    lines.append("")

    if changes["arrivals"]:
        lines.append(f"ARRIVALS ({len(changes['arrivals'])})")
        for item in changes["arrivals"]:
            lines.append(
                f"  ✓ {item['po_number']} L{item['line_number']} — {item['sku']} "
                f"({item['description']}) — {int(item['quantity_received'])} units received"
            )
        lines.append("")

    if changes["partial_arrivals"]:
        lines.append(f"PARTIAL ARRIVALS ({len(changes['partial_arrivals'])})")
        for item in changes["partial_arrivals"]:
            lines.append(
                f"  ~ {item['po_number']} L{item['line_number']} — {item['sku']} "
                f"({item['description']}) — {int(item['qty_increase'])} new units, "
                f"{item['pct_received']}% received"
            )
        lines.append("")

    if changes["date_changes"]:
        lines.append(f"DELIVERY DATE CHANGES ({len(changes['date_changes'])})")
        for item in changes["date_changes"]:
            shift = abs(item["days_shifted"])
            direction = item["direction"]
            lines.append(
                f"  ↕ {item['po_number']} L{item['line_number']} — {item['sku']} "
                f"({item['description']}) — EDD moved {direction} by {shift} day(s): "
                f"{item['previous_date']} → {item['expected_delivery_date']}"
            )
        lines.append("")

    if changes["cancellations"]:
        lines.append(f"CANCELLATIONS / HOLDS ({len(changes['cancellations'])})")
        for item in changes["cancellations"]:
            lines.append(
                f"  ✗ {item['po_number']} L{item['line_number']} — {item['sku']} "
                f"({item['description']}) — Status: {item['previous_status']} → {item['status']}"
            )
        lines.append("")

    if changes["new_items"]:
        lines.append(f"NEW PO LINES ({len(changes['new_items'])})")
        for item in changes["new_items"]:
            lines.append(
                f"  + {item['po_number']} L{item['line_number']} — {item['sku']} "
                f"({item['description']}) — EDD: {item['expected_delivery_date']}"
            )

    return "\n".join(lines)
