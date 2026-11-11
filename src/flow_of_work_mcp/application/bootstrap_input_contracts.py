"""Canonical guided input shapes shared by validation and public discovery."""
from copy import deepcopy


ANSWER_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "answer_key": {"type": "string", "minLength": 1, "maxLength": 120},
        "question": {"type": "string", "minLength": 1, "maxLength": 1000},
        "answer": {"type": "string", "minLength": 1, "maxLength": 4096},
        "kind": {"type": "string", "maxLength": 32, "enum": ["intent", "observation", "proposal"]},
        "source_reference": {"type": "string", "minLength": 1, "maxLength": 1000},
    },
}
ANSWER_SCHEMA["required"] = list(ANSWER_SCHEMA["properties"])

REFERENCES_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        key: {"type": "array", "maxItems": 128, "uniqueItems": True,
              "items": {"type": "string", "minLength": 1, "maxLength": 128}}
        for key in ("requirement_ids", "goal_node_ids", "milestone_ids")
    },
}
REFERENCES_SCHEMA["required"] = list(REFERENCES_SCHEMA["properties"])
REFERENCES_SCHEMA["anyOf"] = [
    {"properties": {key: {"minItems": 1}}}
    for key in REFERENCES_SCHEMA["properties"]
]

CORRESPONDENCE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "answer_key": ANSWER_SCHEMA["properties"]["answer_key"],
        "answer_revision": {"type": "integer", "minimum": 1},
        "canonical_references": REFERENCES_SCHEMA,
        "disposition": {"type": "string", "enum": ["consistent", "needs_clarification", "requires_intent_change"]},
        "rationale": {"type": "string", "minLength": 1, "maxLength": 2000},
    },
}
CORRESPONDENCE_SCHEMA["required"] = list(CORRESPONDENCE_SCHEMA["properties"])

MILESTONE_REVISION_FIELDS = (
    "name", "requirement_ids", "prerequisite_requirement_ids", "entry_policy", "exit_policy", "risk_disposition",
)
MILESTONE_REVISION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["milestone_id", "expected_revision"],
    "anyOf": [{"required": [key]} for key in MILESTONE_REVISION_FIELDS],
    "properties": {
        "milestone_id": {"type": "string", "pattern": "^MILE-[0-9]{6}$"},
        "expected_revision": {"type": "integer", "minimum": 1},
        "name": {"type": "string", "minLength": 1},
        "requirement_ids": {"type": "array", "minItems": 1, "maxItems": 128, "uniqueItems": True,
                            "items": {"type": "string", "pattern": "^REQ-[0-9]{6}$"}},
        "prerequisite_requirement_ids": {"type": "array", "maxItems": 128, "uniqueItems": True,
                                         "items": {"type": "string", "pattern": "^REQ-[0-9]{6}$"}},
        "entry_policy": {"type": "object"},
        "exit_policy": {"type": "object"},
        "risk_disposition": {"type": "string", "minLength": 1},
    },
}


def bootstrap_input_schema(field, *, nullable=False):
    schema = deepcopy({"answer": ANSWER_SCHEMA, "correspondence": CORRESPONDENCE_SCHEMA,
                       "milestone_revision": MILESTONE_REVISION_SCHEMA}[field])
    return {"anyOf": [schema, {"type": "null"}]} if nullable else schema
