from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient


def test_vincular_mesa_cliente_route_reenvia_a_core(client: TestClient):
    payload = {"codigo_qr_mesa": "token_qr_1", "numero_mesa": 5}
    core_response = {
        "mensaje": "Mesa libre. Listo para pedir.",
        "estado_mesa": "LIBRE",
        "numero_mesa": 5,
        "factura_local_uuid_activa": None,
    }

    with patch(
        "app.api.routers.movil_mesas.core_client.post",
        new=AsyncMock(return_value=core_response),
    ) as mocked_post:
        response = client.post("/api/v1/clientes/mesas/vincular", json=payload)

    assert response.status_code == 200
    assert response.headers["X-Data-Source"] == "CORE"
    assert response.json()["estado_mesa"] == "LIBRE"
    mocked_post.assert_awaited_once_with("/api/v1/mesas/vincular", json=payload)


def test_vincular_mesa_legacy_route_sigue_disponible(client: TestClient):
    payload = {"codigo_qr_mesa": "token_qr_legacy", "numero_mesa": 8}
    core_response = {
        "mensaje": "Mesa libre. Listo para pedir.",
        "estado_mesa": "LIBRE",
        "numero_mesa": 8,
        "factura_local_uuid_activa": None,
    }

    with patch(
        "app.api.routers.movil_mesas.core_client.post",
        new=AsyncMock(return_value=core_response),
    ):
        response = client.post("/api/v1/mesas/vincular", json=payload)

    assert response.status_code == 200
    assert response.headers["X-Data-Source"] == "CORE"


def test_vincular_mesa_propagates_error_de_core(client: TestClient):
    payload = {"codigo_qr_mesa": "token_invalido", "numero_mesa": 5}

    with patch(
        "app.api.routers.movil_mesas.core_client.post",
        new=AsyncMock(
            return_value={
                "detail": "Código QR inválido o mesa inactiva.",
                "_status_code": 404,
            }
        ),
    ):
        response = client.post("/api/v1/clientes/mesas/vincular", json=payload)

    assert response.status_code == 404
    assert response.json()["detail"] == "Código QR inválido o mesa inactiva."


def test_vincular_mesa_hace_fallback_local_si_core_esta_offline(client: TestClient):
    payload = {"codigo_qr_mesa": "token_temporal", "numero_mesa": 5}

    with patch(
        "app.api.routers.movil_mesas.core_client.post",
        new=AsyncMock(return_value=None),
    ):
        response = client.post("/api/v1/clientes/mesas/vincular", json=payload)

    assert response.status_code == 200
    assert response.headers["X-Data-Source"] == "CACHE_LOCAL"
    assert response.json()["estado_mesa"] == "LIBRE"


def test_llamar_mesero_cliente_route_reenvia_a_core(client: TestClient):
    with patch(
        "app.api.routers.movil_mesas.core_client.post",
        new=AsyncMock(return_value={"mensaje": "Alerta enviada."}),
    ) as mocked_post:
        response = client.post(
            "/api/v1/clientes/mesas/999/llamar-mesero",
            json={"motivo_llamada": "Asistencia"},
        )

    assert response.status_code == 200
    assert response.headers["X-Data-Source"] == "CORE"
    mocked_post.assert_awaited_once_with(
        "/api/v1/mesas/999/llamar-mesero",
        json={"motivo_llamada": "Asistencia"},
    )
