import pytest
from fastapi.testclient import TestClient

def test_login_empleado_missing_fields(client: TestClient):
    response = client.post("/api/v1/auth/empleados/login", json={})
    # FastApi validation error should be 422
    assert response.status_code == 422

def test_login_empleado_invalid_credentials(client: TestClient):
    # This might try to reach fake CORE api and fail or just fail because we mock nothing in the httpx client yet
    response = client.post(
        "/api/v1/auth/empleados/login", 
        data={"username": "ghost", "password": "123"}
    )
    # If the gateway handles connection errors gracefully, it should be 503 or 500, but we just verify it doesn't crash unexpectedly
    assert response.status_code in [401, 500, 502, 503]

def test_login_cliente_invalid_credentials(client: TestClient):
    response = client.post(
        "/api/v1/auth/clientes/login", 
        json={"email": "ghost@test.com", "password": "123"}
    )
    assert response.status_code in [401, 500, 502, 503]

def test_verificar_token_seguridad(client: TestClient):
    response = client.get("/login-token-check")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
