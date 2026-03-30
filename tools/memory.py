# ============================================================
# tools/memory.py — Persistent CRM Memory
# ============================================================
# Lets the agent save what it learns about the CRM so it
# doesn't have to rediscover things every session.
# ============================================================

import os
import json

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
