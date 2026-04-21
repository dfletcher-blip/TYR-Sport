# ============================================================
# wip_agent.py — WIP Receive Report AI Agent
# ============================================================
# Fetches the WIP receive report from ACS, compares it against
# the last known snapshot to detect changes (arrivals, delivery
# date shifts, cancellations), then uses Claude to write a
# human-friendly summary and sends email notifications.
#
# Usage: called by run_wip_agent.py — do not run directly.
# ============================================================

import json
import os
from datetime import datetime

import anthropic
from dotenv import load_dotenv

from tools.acs_api import fetch_wip_report
from tools.wip_report import (
    detect_wip_changes,
    format_change_summary,
    get_snapshot_age,
    load_wip_snapshot,
    save_wip_snapshot,
)
from tools.wip_notifications import get_notify_recipients, send_wip_notification

load_dotenv()


# ── System prompt ──────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are the WIP Receive Report Agent for TYR Sport.

Your job is to analyze changes in the WIP (Work In Progress) receive report
from the ACS ERP system and communicate them clearly to the purchasing and
operations teams.

When given a set of detected changes, you:
1. Write a concise, actionable summary of what happened
2. Highlight the most important items (urgent arrivals, large date shifts, cancellations)
3. Note any patterns (e.g., multiple lines from the same vendor all delayed)
4. Flag anything that needs immediate attention
5. Keep the tone professional and direct — this goes to buyers and operations staff

Your summary will be embedded in an automated email alert. Keep it to 3-6 sentences
or a short bulleted list. Do not repeat every item in detail — the email tables
do that already. Focus on the "so what" and any recommended actions.

You do NOT have access to external tools in this loop. Just analyze the data
you are given and produce a clear written summary."""


# ── Tool definitions for Claude ────────────────────────────────────────────────

TOOL_DEFINITIONS = [
    {
        "name": "fetch_wip_report",
        "description": (
            "Fetch the current WIP receive report from the ACS ERP system. "
            "Returns a list of open purchase order lines with quantities, "
            "expected delivery dates, and receipt status."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "load_wip_snapshot",
        "description": (
            "Load the previously saved WIP snapshot from disk. "
            "Returns a dict keyed by PO::line::SKU with the last known state of each item. "
            "Returns an empty dict if no snapshot exists (first run)."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "detect_wip_changes",
        "description": (
            "Compare the current WIP report against the previous snapshot and identify "
            "what changed: arrivals (items fully received), partial arrivals (quantity "
            "increased but not complete), delivery date changes, new PO lines, and "
            "cancellations or holds."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "current_items": {
                    "type": "array",
                    "description": "The list of items returned by fetch_wip_report",
                },
                "previous_snapshot": {
                    "type": "object",
                    "description": "The dict returned by load_wip_snapshot",
                },
            },
            "required": ["current_items", "previous_snapshot"],
        },
    },
    {
        "name": "save_wip_snapshot",
        "description": (
            "Save the current WIP report as the new baseline snapshot. "
            "Call this AFTER detecting changes so the next run has an accurate baseline. "
            "Pass the same list of items returned by fetch_wip_report."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "description": "The current WIP items to persist as the new snapshot",
                },
            },
            "required": ["items"],
        },
    },
    {
        "name": "send_wip_notification",
        "description": (
            "Send an email alert to the configured recipients listing all detected changes. "
            "Include an 'ai_summary' with your analysis to appear at the top of the email. "
            "Set dry_run=True to preview the email without sending."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "changes": {
                    "type": "object",
                    "description": "The changes dict returned by detect_wip_changes",
                },
                "ai_summary": {
                    "type": "string",
                    "description": "Your concise analysis of the changes to embed in the email",
                },
                "dry_run": {
                    "type": "boolean",
                    "description": "If true, print the email but do not send it",
                },
            },
            "required": ["changes"],
        },
    },
]


# ── Tool dispatcher ────────────────────────────────────────────────────────────

def _dispatch_tool(tool_name: str, tool_input: dict):
    if tool_name == "fetch_wip_report":
        return fetch_wip_report()

    if tool_name == "load_wip_snapshot":
        return load_wip_snapshot()

    if tool_name == "detect_wip_changes":
        return detect_wip_changes(
            tool_input["current_items"],
            tool_input["previous_snapshot"],
        )

    if tool_name == "save_wip_snapshot":
        save_wip_snapshot(tool_input["items"])
        return {"saved": True, "item_count": len(tool_input["items"])}

    if tool_name == "send_wip_notification":
        return send_wip_notification(
            changes=tool_input["changes"],
            ai_summary=tool_input.get("ai_summary", ""),
            dry_run=tool_input.get("dry_run", False),
        )

    return {"error": f"Unknown tool: {tool_name}"}


# ── Logging ────────────────────────────────────────────────────────────────────

def _log_run(result: dict, changes: dict) -> None:
    os.makedirs("logs", exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = os.path.join("logs", f"wip_run_{timestamp}.json")
    with open(log_path, "w") as f:
        json.dump(
            {
                "run_at": datetime.utcnow().isoformat() + "Z",
                "changes_detected": changes.get("total_changes", 0),
                "result": result,
                "change_summary": {
                    "arrivals": len(changes.get("arrivals", [])),
                    "partial_arrivals": len(changes.get("partial_arrivals", [])),
                    "date_changes": len(changes.get("date_changes", [])),
                    "cancellations": len(changes.get("cancellations", [])),
                    "new_items": len(changes.get("new_items", [])),
                },
            },
            f,
            indent=2,
        )


# ── Agent loop ─────────────────────────────────────────────────────────────────

def run_wip_agent(
    dry_run: bool = False,
    force_notify: bool = False,
    notify_new_items: bool = False,
) -> str:
    """
    Run one complete WIP monitoring cycle:
      1. Fetch current report from ACS
      2. Load last snapshot
      3. Detect changes
      4. Save new snapshot
      5. If changes found (or force_notify=True), ask Claude to analyze
         and send an email notification

    dry_run        — Detect changes and preview email without sending
    force_notify   — Send notification even if no changes detected
    notify_new_items — Include new PO lines in notification even on first run

    Returns a human-readable summary string.
    """
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    snapshot_age = get_snapshot_age()
    recipients = get_notify_recipients()

    # Build the task description for Claude
    context_parts = [
        "You are running the WIP Receive Report monitoring cycle for TYR Sport.",
    ]
    if snapshot_age:
        context_parts.append(f"The last snapshot was saved {snapshot_age}.")
    else:
        context_parts.append("This is the FIRST run — there is no previous snapshot yet.")

    if recipients:
        context_parts.append(f"Notifications will be sent to: {', '.join(recipients)}.")
    else:
        context_parts.append("WARNING: WIP_NOTIFY_EMAILS is not configured — no emails will be sent.")

    if dry_run:
        context_parts.append("DRY RUN MODE: Detect changes and preview the email, but do NOT send it.")

    if force_notify:
        context_parts.append("FORCE NOTIFY: Send a notification even if there are no changes.")

    context_parts.append(
        "\nPlease complete the following steps in order:\n"
        "1. Call fetch_wip_report to get the current report\n"
        "2. Call load_wip_snapshot to get the previous baseline\n"
        "3. Call detect_wip_changes with both results\n"
        "4. Call save_wip_snapshot to update the baseline with the current data\n"
        "5. If changes were found"
        + (" (or because force_notify=True)" if force_notify else "")
        + ": write a concise AI summary of the changes, then call send_wip_notification\n"
        "6. Report what happened in plain English"
    )

    if not notify_new_items and not snapshot_age:
        context_parts.append(
            "\nSince this is the first run, skip sending a notification — just save the snapshot "
            "and report how many items were found. New items on first run are not changes."
        )

    task = " ".join(context_parts)

    messages = [{"role": "user", "content": task}]
    detected_changes: dict = {}

    print("\n[WIP Agent] Starting monitoring cycle...")

    while True:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=TOOL_DEFINITIONS,
            messages=messages,
        )

        # Collect any text the agent produces
        text_content = ""
        tool_calls = []

        for block in response.content:
            if block.type == "text":
                text_content += block.text
            elif block.type == "tool_use":
                tool_calls.append(block)

        if text_content:
            print(f"[WIP Agent] {text_content.strip()}")

        # Stop when the agent is done
        if response.stop_reason == "end_turn":
            break

        # No tool calls and not end_turn means something unexpected happened
        if not tool_calls:
            break

        # Execute each tool call and feed results back
        tool_results = []
        for tc in tool_calls:
            print(f"[WIP Agent] → {tc.name}(...)")
            result = _dispatch_tool(tc.name, tc.input)

            # Capture the changes dict for logging
            if tc.name == "detect_wip_changes":
                detected_changes = result
                summary = format_change_summary(result)
                print(summary)

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tc.id,
                "content": json.dumps(result, default=str),
            })

        # Append assistant message and tool results to conversation
        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results})

    # Log this run
    _log_run({"dry_run": dry_run, "force_notify": force_notify}, detected_changes)

    return text_content or "WIP monitoring cycle complete."
