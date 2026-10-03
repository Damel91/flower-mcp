"""Bounded provider-neutral declarations and external evidence schemas."""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Mapping

from flow_of_work_mcp.core.domain.paths import repo_relative_file_path

CONTRACT_KINDS = frozenset({'symbol', 'api', 'data_shape', 'protocol', 'behavioral_boundary'})
VERIFICATION_KINDS = frozenset({'unit_check', 'deterministic_campaign', 'live_campaign', 'oracle', 'explicit_authority'})


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def fingerprint(value: object) -> str:
    return sha256(canonical_json(value).encode()).hexdigest()


def text(value: object, name: str, *, required: bool = True) -> str:
    if not isinstance(value, str):
        raise ValueError(f'{name} must be text')
    value = value.strip()
    if (required and not value) or len(value) > 4096:
        raise ValueError(f'{name} must be nonempty bounded text')
    return value


def number(value: object, name: str = 'criterion') -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f'{name} must be a positive integer')
    return value


def objects(value: object, name: str, *, max_items: int = 128) -> list[Mapping[str, object]]:
    if not isinstance(value, (list, tuple)) or len(value) > max_items:
        raise ValueError(f'{name} must be a bounded list')
    if any(not isinstance(item, Mapping) for item in value):
        raise ValueError(f'{name} must contain objects')
    return list(value)


def strings(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or len(value) > 128:
        raise ValueError(f'{name} must be a bounded list')
    result = tuple(text(item, name) for item in value)
    if len(set(result)) != len(result):
        raise ValueError(f'{name} must not contain duplicates')
    return result


def fields(value: Mapping[str, object], allowed: set[str], name: str) -> None:
    unknown = set(value) - allowed
    if unknown:
        raise ValueError(f'{name} contains unsupported fields: {", ".join(sorted(unknown))}')


@dataclass(frozen=True)
class PlannedContract:
    name: str
    kind: str
    clauses: tuple[str, ...]
    file_path: str = ''
    symbol: str = ''
    signature: str = ''

    @classmethod
    def from_payload(cls, value: Mapping[str, object]) -> 'PlannedContract':
        fields(value, {'name', 'kind', 'clauses', 'file_path', 'symbol', 'signature'}, 'provides')
        kind = text(value.get('kind'), 'kind')
        if kind not in CONTRACT_KINDS:
            raise ValueError('unsupported planned contract kind')
        clauses = strings(value.get('clauses'), 'clauses')
        if not clauses:
            raise ValueError('planned contract clauses must not be empty')
        return cls(text(value.get('name'), 'name'), kind, clauses,
                   repo_relative_file_path(text(value.get('file_path', ''), 'file_path', required=False)),
                   text(value.get('symbol', ''), 'symbol', required=False),
                   text(value.get('signature', ''), 'signature', required=False))

    def as_payload(self) -> dict[str, object]:
        return {'name': self.name, 'kind': self.kind, 'clauses': list(self.clauses),
                **{key: value for key, value in {'file_path': self.file_path, 'symbol': self.symbol,
                                                'signature': self.signature}.items() if value}}


@dataclass(frozen=True)
class ContractUse:
    producer_unit_key: str
    contract_name: str
    use: str

    @classmethod
    def from_payload(cls, value: Mapping[str, object]) -> 'ContractUse':
        fields(value, {'producer_unit_key', 'contract_name', 'use'}, 'requires')
        return cls(text(value.get('producer_unit_key'), 'producer_unit_key'),
                   text(value.get('contract_name'), 'contract_name'), text(value.get('use'), 'use'))

    def as_payload(self) -> dict[str, object]:
        return {'producer_unit_key': self.producer_unit_key, 'contract_name': self.contract_name,
                'use': self.use}


@dataclass(frozen=True)
class VerificationIntent:
    criterion: int
    kind: str
    statement: str
    authority_ref: str = ''

    @classmethod
    def from_payload(cls, value: Mapping[str, object]) -> 'VerificationIntent':
        fields(value, {'criterion', 'kind', 'statement', 'authority_ref'}, 'verifies')
        kind = text(value.get('kind'), 'kind')
        if kind not in VERIFICATION_KINDS:
            raise ValueError('unsupported verification kind')
        authority = text(value.get('authority_ref', ''), 'authority_ref', required=False)
        if kind == 'explicit_authority' and not authority:
            raise ValueError('explicit_authority verification requires authority_ref')
        return cls(number(value.get('criterion')), kind, text(value.get('statement'), 'statement'), authority)

    def as_payload(self) -> dict[str, object]:
        return {'criterion': self.criterion, 'kind': self.kind, 'statement': self.statement,
                **({'authority_ref': self.authority_ref} if self.authority_ref else {})}


def normalize_declarations(value: Mapping[str, object]) -> dict[str, object]:
    implements = value.get('implements', [])
    if not isinstance(implements, (list, tuple)) or len(implements) > 128:
        raise ValueError('implements must be a bounded list')
    implements = [number(item) for item in implements]
    if len(set(implements)) != len(implements):
        raise ValueError('implements must not contain duplicates')
    provides = [PlannedContract.from_payload(item).as_payload() for item in objects(value.get('provides', []), 'provides')]
    requires = [ContractUse.from_payload(item).as_payload() for item in objects(value.get('requires', []), 'requires')]
    verifies = [VerificationIntent.from_payload(item).as_payload() for item in objects(value.get('verifies', []), 'verifies')]
    if len({item['name'] for item in provides}) != len(provides):
        raise ValueError('planned contract names must be unique in a producer unit')
    if len({(item['producer_unit_key'], item['contract_name']) for item in requires}) != len(requires):
        raise ValueError('contract uses must be unique in a consumer unit')
    if len({(item['criterion'], item['kind'], item['statement']) for item in verifies}) != len(verifies):
        raise ValueError('verification intents must be unique')
    return {'implements': implements, 'provides': provides, 'requires': requires, 'verifies': verifies}
