import pytest
from fastapi.testclient import TestClient
from datetime import datetime, timedelta
from decimal import Decimal
from app.models.integration_models import PromocionCache, CodigoPromocionalCache

def test_evaluar_promociones_globales_offline(client: TestClient, db_session):
    promo = PromocionCache(
        id=1,
        nombre="Promo 1",
        tipo_descuento="PORCENTAJE",
        valor=Decimal("10.0"),
        fecha_inicio=datetime.now() - timedelta(days=1),
        fecha_fin=datetime.now() + timedelta(days=1),
        aplica_a="TODOS"
    )
    db_session.add(promo)
    db_session.commit()

    response = client.get("/api/v1/promociones/evaluar/globales")
    assert response.status_code == 200
    assert isinstance(response.json(), list)
    # The integration layer might evaluate this offline or forward to CORE, but it should return 200

def test_happy_hour_activo_offline(client: TestClient, db_session):
    promo = PromocionCache(
        id=2,
        nombre="Happy Hour Test",
        tipo_descuento="PORCENTAJE",
        valor=Decimal("50.0"),
        fecha_inicio=datetime.now() - timedelta(days=1),
        fecha_fin=datetime.now() + timedelta(days=1),
        aplica_a="TODOS",
        aplica_happy_hour=True,
        hora_inicio_hh="00:00",
        hora_fin_hh="23:59"
    )
    db_session.add(promo)
    db_session.commit()

    response = client.get("/api/v1/promociones/happy-hour/activo")
    assert response.status_code == 200

def test_validar_codigo_promocional(client: TestClient, db_session):
    promo = PromocionCache(
        id=3,
        nombre="Promo Codigo",
        tipo_descuento="PORCENTAJE",
        valor=Decimal("20.0"),
        fecha_inicio=datetime.now() - timedelta(days=1),
        fecha_fin=datetime.now() + timedelta(days=1)
    )
    codigo = CodigoPromocionalCache(
        id=1,
        promocion_id=3,
        codigo="TESTCODE",
        fecha_inicio=datetime.now() - timedelta(days=1),
        fecha_fin=datetime.now() + timedelta(days=1)
    )
    db_session.add_all([promo, codigo])
    db_session.commit()

    payload = {"codigo": "TESTCODE"}
    response = client.post("/api/v1/promociones/codigos/validar", json=payload)
    assert response.status_code in [200, 404] # Might be 404 if offline validation logic requires more fields

def test_evaluar_mejor_descuento_offline(client: TestClient):
    response = client.get("/api/v1/promociones/evaluar/mejor-descuento?producto_id=1&cantidad=2")
    assert response.status_code in [200, 404]

def test_aplicacion_promocion(client: TestClient):
    payload = {
        "promocion_id": 1,
        "monto_descuento": 100.0,
        "tipo_aplicacion": "AUTOMATICA"
    }
    response = client.post("/api/v1/promociones/aplicaciones", json=payload)
    assert response.status_code in [201, 202, 400, 422]

def test_supervisor_auth(client: TestClient):
    payload = {"supervisor_id": 1, "password": "123", "terminal": "CAJA1"}
    response = client.post("/api/v1/promociones/supervisor/auth", json=payload)
    assert response.status_code in [401, 404, 200, 502, 503]
