# ============================================================
# tools/memory.py — Persistent CRM Memory
# ============================================================
# Lets the agent save what it learns about the CRM so it
# doesn't have to rediscover things every session.
#
# Two types of memory:
#   1. CRM facts  — field names, entity names, known quirks
#   2. Conversation history — summaries of past sessions so
#      the agent remembers what was discussed and decided
# ============================================================

import os
import json
from datetime import datetime, timezone

MEMORY_PATH = os.path.join(os.path.dirname(__file__), "..", "crm_memory.json")


def update_crm_memory(section: str, key: str, value) -> dict:
    """
    Save something to the agent's persistent CRM memory.
    Use this when you discover something useful about this CRM that
    you'd want to remember next session — field names, entity names,
    user IDs, common patterns, etc.

    section: top-level section in memory (e.g. "key_fields", "agent_notes", "known_views")
    key:     the key within that section (e.g. "special_terms_entity_name")
    value:   the value to store (string, list, dict, etc.)
    """
    try:
        if os.path.exists(MEMORY_PATH):
            with open(MEMORY_PATH, "r") as f:
                memory = json.load(f)
        else:
            memory = {}

        if section not in memory:
            memory[section] = {}

        if isinstance(memory[section], dict):
            memory[section][key] = value
        elif isinstance(memory[section], list):
            if value not in memory[section]:
                memory[section].append(value)
        else:
            memory[section] = {key: value}

        with open(MEMORY_PATH, "w") as f:
            json.dump(memory, f, indent=2)

        return {"success": True, "message": f"Saved {section}.{key} to CRM memory."}

    except Exception as e:
        return {"success": False, "error": str(e)}


def read_crm_memory() -> dict:
    """
    Read the full CRM memory file. Use this to check what the agent
    already knows about this CRM.
    """
    try:
        if not os.path.exists(MEMORY_PATH):
            return {"success": True, "memory": {}, "message": "No memory file found yet."}
        with open(MEMORY_PATH, "r") as f:
            memory = json.load(f)
        return {"success": True, "memory": memory}
    except Exception as e:
        return {"success": False, "error": str(e)}


def save_session_summary(summary: str, actions_taken: list = None, decisions_made: list = None) -> dict:
    """
    Save a summary of this conversation session to persistent memory.
    Call this at the end of a session or whenever something important
    was discussed or decided that should be remembered next time.

    summary:         2-4 sentence description of what was discussed and done
    actions_taken:   list of specific things that were changed in the CRM
    decisions_made:  list of decisions or preferences the user expressed
                     (e.g. "user prefers dashboards sorted by owner")

    Returns confirmation the summary was saved.
    """
    try:
        if os.path.exists(MEMORY_PATH):
            with open(MEMORY_PATH, "r") as f:
                memory = json.load(f)
        else:
            memory = {}

        if "conversation_history" not in memory:
            memory["conversation_history"] = []

        entry = {
            "date":            datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "summary":         summary,
            "actions_taken":   actions_taken or [],
            "decisions_made":  decisions_made or [],
        }

        # Keep the last 20 session summaries
        memory["conversation_history"].insert(0, entry)
        memory["conversation_history"] = memory["conversation_history"][:20]

        with open(MEMORY_PATH, "w") as f:
            json.dump(memory, f, indent=2)

        return {"success": True, "message": "Session summary saved to memory."}

    except Exception as e:
        return {"success": False, "error": str(e)}


def get_conversation_history(limit: int = 5) -> dict:
    """
    Read the summaries of past conversation sessions.
    Use this at the start of a session to recall what was previously
    discussed, what changes were made, and what the user prefers.

    limit: how many past sessions to return (default 5, max 20)

    Returns recent session summaries in reverse chronological order.
    """
    try:
        if not os.path.exists(MEMORY_PATH):
            return {"success": True, "history": [], "message": "No conversation history yet."}

        with open(MEMORY_PATH, "r") as f:
            memory = json.load(f)

        history = memory.get("conversation_history", [])[:limit]

        return {
            "success":       True,
            "total_sessions": len(memory.get("conversation_history", [])),
            "showing":       len(history),
            "history":       history,
        }

    except Exception as e:
        return {"success": False, "error": str(e)}
