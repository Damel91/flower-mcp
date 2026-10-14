from __future__ import annotations

from types import SimpleNamespace

import pytest

from flow_of_work_mcp.adapters.implementation_intelligence.mcp_transport_worker import (
    _decode_mcp_result, ProviderResponseContractError,
)


def test_provider_decoder_accepts_structured_content_without_reading_markdown() -> None:
    response = SimpleNamespace(
        structuredContent={"result": {"status": "ready", "revision": 7}},
        content=[SimpleNamespace(text="# deliberately unrelated\n")],
    )

    assert _decode_mcp_result(response) == {
        "result": {"status": "ready", "revision": 7}
    }


def test_provider_decoder_rejects_json_text_without_structured_content() -> None:
    response = SimpleNamespace(
        structuredContent=None,
        content=[SimpleNamespace(text='{"result":{"status":"ready"}}')],
    )

    with pytest.raises(
        ProviderResponseContractError,
        match="lacks structured content",
    ):
        _decode_mcp_result(response)
