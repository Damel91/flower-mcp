"""Wire guidance for canonical refs; runtime validation stays in the handler."""
from flow_of_work_mcp.core.domain.architecture import ENTITY_ID_PATTERN, ENTITY_KINDS


def architecture_refs_input_schema():
    return {'anyOf': [{'type': 'array', 'maxItems': 128, 'uniqueItems': True,
        'items': {'type': 'object', 'additionalProperties': False,
                  'required': ['revision', 'kind', 'entity_id'],
                  'properties': {'revision': {'type': 'integer', 'minimum': 1, 'maximum': 2**63 - 1},
                                 'kind': {'type': 'string', 'enum': list(ENTITY_KINDS)},
                                 'entity_id': {'type': 'string', 'pattern': ENTITY_ID_PATTERN}}}},
                      {'type': 'null'}]}
