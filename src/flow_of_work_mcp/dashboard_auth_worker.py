"""One bounded native credential request over private stdin/stdout pipes."""
from __future__ import annotations

import json
from pathlib import Path
import sys

# An absolute script invocation with python -I has no package search root.
# Select only this worker's adjacent source/installed package, never cwd/env.
if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flow_of_work_mcp import dashboard_auth_native as native


def _closed_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('duplicate field')
        value[key] = item
    return value


def decode_request(raw: bytes) -> dict:
    if not raw or len(raw) > native.MAX_REQUEST_BYTES:
        raise ValueError('invalid request size')
    value = json.loads(raw.decode('utf-8'), object_pairs_hook=_closed_object,
                       parse_constant=lambda _: (_ for _ in ()).throw(ValueError('invalid constant')))
    if isinstance(value, dict) and value.get('contract') == native.CAPABILITY_CONTRACT:
        return native.validate_capability_request(value)
    return native.validate_request(value)


def process(raw: bytes) -> dict:
    try:
        request = decode_request(raw)
        if request['contract'] == native.CAPABILITY_CONTRACT:
            response = {'contract': native.CAPABILITY_CONTRACT, **native.capability(request['owner'])}
            native.validate_capability_reply(response)
            return response
        result = native.verify(request['owner'], request['username'], request['password'])
        response = {'contract': native.CONTRACT, **result}
        native.validate_reply(response, request['owner'])
        return response
    except Exception:
        return {'contract': native.CONTRACT, 'outcome': 'error', 'identity': None, 'reason': 'protocol_invalid'}


def main() -> int:
    raw = sys.stdin.buffer.read(native.MAX_REQUEST_BYTES + 1)
    response = process(raw)
    encoded = json.dumps(response, ensure_ascii=True, separators=(',', ':')).encode('utf-8')
    if len(encoded) > native.MAX_REPLY_BYTES:
        encoded = b'{"contract":"flow.dashboard.native_auth.v1","outcome":"error","identity":null,"reason":"protocol_invalid"}'
    sys.stdout.buffer.write(encoded + b'\n')
    sys.stdout.buffer.flush()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
