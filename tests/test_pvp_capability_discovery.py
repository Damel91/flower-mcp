"""Capability observations cannot turn health or malformed envelopes into support."""
from copy import deepcopy

import pytest

from flow_of_work_mcp.adapters.implementation_intelligence.packet_provider import McpCodingCastlePacketProvider
from flow_of_work_mcp.application.packet_executor import PacketExecutorService
from tests.test_packet_executor import CAPABILITY, fixture, negotiate, select
from tests.test_packet_provider_port import _Client


def _negotiator(tmp_path, payload):
    ledger, external, _, _, ids, revs = fixture(tmp_path)
    client = _Client(payload)
    adapter = McpCodingCastlePacketProvider(client=client, bindings=(), binding_resolver=ledger)
    service = PacketExecutorService(ledger, provider=adapter, semantic_projection=external.provider_validation)
    select(service, ids, revs)
    return ledger, service, client, ids, revs


def _registry(*, advertised=True):
    return {'contract_version': 'codingcastle.capabilities.v2',
            **({'packet_validation': deepcopy(CAPABILITY)} if advertised else {})}


def _overview(available, *, advertised=False):
    return {'contract_version': 'codingcastle.orientation.v2', 'group': 'overview',
            'status': {'available': available, 'model_health': 'fixture-health'},
            **({'packet_validation': deepcopy(CAPABILITY)} if advertised else {})}


def _wrapped(value, count):
    for _ in range(count):
        value = {'status': 'success', 'result': value}
    return value


@pytest.mark.parametrize('payload', [
    _registry(), {'result': _registry()}, _wrapped(_registry(), 3),
    {'status': 'ok', 'result': {'packet_validation': CAPABILITY}},
], ids=['registry', 'structured-wrapper', 'maximum-depth', 'existing-success-wrapper'])
def test_explicit_registry_route_support_and_exact_replay(tmp_path, payload):
    ledger, service, client, ids, revs = _negotiator(tmp_path, payload)
    result = negotiate(service, ids, revs)
    assert result['status'] == 'success'
    assert result['capability']['capability'] == CAPABILITY
    assert service.admission(*ids)['allowed'] is True
    assert negotiate(service, ids, revs) == result
    assert client.calls == [('codingcastle_capabilities', {'group': 'all'})]
    assert ledger.packet_provider_outbox_entries(*ids) == []


@pytest.mark.parametrize('payload', [
    _registry(advertised=False), {'result': _registry(advertised=False)},
    _overview(True), _overview(False), {'result': _overview(True)},
    _overview(True, advertised=True), _overview(False, advertised=True),
    {'packet_validation': []}, {'packet_validation': {'supported': True}},
    {'packet_validation': {**CAPABILITY, 'receipt_versions': ['codingcastle.packet.receipt.v2']}},
], ids=['absent', 'wrapped-absent', 'available-overview', 'unavailable-overview',
        'wrapped-overview', 'overview-cannot-advertise', 'unavailable-cannot-advertise',
        'malformed-ad', 'invented-support', 'legacy-receipt-only'])
def test_absent_or_incompatible_capability_is_unsupported_not_rejected(tmp_path, payload):
    ledger, service, client, ids, revs = _negotiator(tmp_path, payload)
    result = negotiate(service, ids, revs)
    assert result['status'] == 'blocked'
    assert result['reason'] == 'provider_validation_projection_unsupported'
    assert result['paired_qualification'] == 'pending'
    assert result['capability']['supported'] is False
    assert service.admission(*ids)['allowed'] is False
    assert negotiate(service, ids, revs) == result
    assert client.calls == [('codingcastle_capabilities', {'group': 'all'})]
    assert ledger.packet_provider_outbox_entries(*ids) == []


@pytest.mark.parametrize('patch', [
    {'status': {'available': True}}, {'status': []}, {'status': True}, {'status': None},
    {'status': ''}, {'status': '   '}, {'result': None}, {'result': []}, {'result': 'invalid'},
    {'status': {'available': True}, 'contract_version': 'codingcastle.orientation.v2', 'group': 'other'},
    {'status': {'available': 'true'}, 'contract_version': 'codingcastle.orientation.v2', 'group': 'overview'},
    {'status': 'success', 'contract_version': 'codingcastle.orientation.v2', 'group': 'overview'},
    {**_overview(True), 'result': _registry()},
], ids=['unknown-health', 'list-status', 'boolean-status', 'null-status', 'empty-status',
        'blank-status', 'null-result', 'list-result', 'scalar-result', 'wrong-overview-group',
        'nonboolean-health', 'overview-with-verdict', 'overview-with-result'])
def test_malformed_envelopes_are_contract_errors_even_with_valid_sibling_ad(tmp_path, patch):
    payload = {**_registry(), **patch}
    ledger, service, client, ids, revs = _negotiator(tmp_path, payload)
    result = negotiate(service, ids, revs)
    assert result['status'] == 'blocked'
    assert result['reason'] == 'implementation_provider_contract_invalid'
    assert result['capability']['supported'] is False
    assert service.admission(*ids)['allowed'] is False
    assert len(client.calls) == 1
    assert ledger.packet_provider_outbox_entries(*ids) == []


@pytest.mark.parametrize('payload', [
    {'status': 'blocked', 'reason': 'provider_policy_refused', 'result': _registry()},
    {'status': 'success', 'result': {'status': 'error', 'reason': 'provider_policy_refused', 'result': _registry()}},
    {'contract_version': 'codingcastle.capabilities.v2', 'status': 'rejected',
     'reason': 'provider_policy_refused', 'packet_validation': CAPABILITY},
], ids=['outer', 'nested', 'contract-version-does-not-bypass-verdict'])
def test_explicit_negative_envelopes_cannot_be_bypassed(tmp_path, payload):
    ledger, service, client, ids, revs = _negotiator(tmp_path, payload)
    result = negotiate(service, ids, revs)
    assert result['status'] == 'blocked'
    assert result['reason'] == 'provider_policy_refused'
    assert service.admission(*ids)['allowed'] is False
    assert len(client.calls) == 1
    assert ledger.packet_provider_outbox_entries(*ids) == []


def test_too_deep_capability_envelope_is_contract_invalid(tmp_path):
    ledger, service, _, ids, revs = _negotiator(tmp_path, _wrapped(_registry(), 4))
    result = negotiate(service, ids, revs)
    assert result['reason'] == 'implementation_provider_contract_invalid'
    assert ledger.packet_provider_outbox_entries(*ids) == []
