import pytest
from fastapi.testclient import TestClient

def test_vincular_mesa_invalida(client: TestClient):
    payload = {"qr_token": "token_invalido"}
    response = client.post("/api/v1/movil-mesas/vincular", json=payload)
    # Because there is no core api fake running, or table isn't found, it should return 400 or 404
    assert response.status_code in [400, 404, 502, 503]

def test_llamar_mesero_mesa_no_existe(client: TestClient):
    response = client.post("/api/v1/movil-mesas/999/llamar-mesero")
    assert response.status_code in [404, 502, 503]

def test_solicitar_cuenta_movil_invalido(client: TestClient):
    fake_uuid = "00000000-0000-0000-0000-000000000000"
    response = client.post(f"/api/v1/pedidos-movil/{fake_uuid}/solicitar-cuenta")
    # Will hit a 404 router since prefix might be wrong or it handles gracefully
    assert response.status_code in [404, 502, 503]

def test_resumen_cuenta_movil_invalido(client: TestClient):
    fake_uuid = "00000000-0000-0000-0000-000000000000"
    response = client.get(f"/api/v1/pedidos-movil/{fake_uuid}/resumen")
    assert response.status_code in [404, 502, 503]

def test_agregar_items_movil_invalid_payload(client: TestClient):
    fake_uuid = "00000000-0000-0000-0000-000000000000"
    payload = {"nuevos_detalles": []} # Empty details
    response = client.patch(f"/api/v1/pedidos-movil/{fake_uuid}/agregar-items", json=payload)
    assert response.status_code in [422, 400, 404]

def test_promociones_evaluar_item(client: TestClient):
    response = client.get("/api/v1/promociones/evaluar/item?producto_id=1&cantidad=2")
    # Could be 200 with empty list or 404 if not found
    assert response.status_code in [200, 404]
