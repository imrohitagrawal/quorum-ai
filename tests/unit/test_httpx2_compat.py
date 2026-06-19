import httpx

import httpx2


def test_httpx2_shim_reexports_httpx_client_types() -> None:
    assert httpx2.Client is httpx.Client
    assert httpx2.BaseTransport is httpx.BaseTransport
    assert httpx2.ASGITransport is httpx.ASGITransport
