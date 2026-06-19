from fastapi.testclient import TestClient


def start_session(client: TestClient) -> dict[str, str]:
    response = client.get("/v1/session")
    response.raise_for_status()
    body = response.json()
    return {"x-csrf-token": body["csrf_token"]}
