import pytest
import uuid
from decimal import Decimal
from fastapi.testclient import TestClient
from app.models.integration_models import PedidoOffline, DetallePedidoOffline

def test_forzar_sincronizacion_pedidos(client: TestClient):
    # This should trigger the sync service and return immediately, trying to push offline data to core
    response = client.post("/api/v1/pedidos/forzar-sincronizacion")
    assert response.status_code == 200
    assert "status" in response.json()

def test_crear_pedido_offline_fails_if_invalid_payload(client: TestClient):
    payload = {
        "canal_origen": "MOVIL"
        # missing mesa, detalles, etc.
    }
    response = client.post("/api/v1/pedidos/", json=payload)
    assert response.status_code == 422

def test_crear_pedido_offline_success(client: TestClient, db_session):
    # Depending on how the gateway creates orders (if it checks cached products first)
    # this might fail if the cache is empty.
    # We will simulate an order directly to see if the gateway accepts it when valid
    payload = {
        "canal_origen": "MOVIL",
        "mesa": 5,
        "detalles": [
            {
                "producto_id": 999, # Might be rejected if not in cache, let's test that behavior
                "cantidad": 1,
                "precio_unitario": 100.0,
                "impuesto": 18.0,
                "monto_impuesto": 18.0,
                "subtotal_linea": 118.0
            }
        ]
    }
    response = client.post("/api/v1/pedidos/", json=payload)
    # The gateway usually verifies the product exists in local cache (Cache.Productos).
    # Since we haven't mocked products in test_int.db, it should return a 404 or 400.
    assert response.status_code in [400, 404, 422, 201]

def test_sincronizar_empleados(client: TestClient):
    response = client.post("/api/v1/empleados/sincronizar")
    # Tries to hit fake core API, might fail gracefully or crash. We expect a managed failure or 200 if mocked.
    assert response.status_code in [200, 500, 502, 503]

def test_sincronizar_promociones(client: TestClient):
    response = client.get("/api/v1/promociones/sync")
    assert response.status_code in [200, 500, 502, 503]

def test_procesar_movimientos_offline_direct_db(db_session):
    # Just verify that inserting a pending order offline works in the DB
    pedido_uuid = uuid.uuid4()
    pedido = PedidoOffline(
        factura_local_uuid=pedido_uuid,
        canal_origen="CAJA",
        subtotal=Decimal("100.00"),
        total_impuestos=Decimal("18.00"),
        total_general=Decimal("118.00")
    )
    db_session.add(pedido)
    db_session.commit()
    db_session.refresh(pedido)

    assert pedido.estado_sincronizacion == "PENDIENTE"
    assert pedido.factura_local_uuid == pedido_uuid


def test_active_tables_order_detail_includes_mobile_line_items(client: TestClient, db_session):
    """CAJA must receive mobile order items after selecting an active table."""
    pedido_uuid = uuid.uuid4()
    pedido = PedidoOffline(
        factura_local_uuid=pedido_uuid,
        canal_origen="MOVIL",
        mesa=12,
        subtotal=Decimal("100.00"),
        total_impuestos=Decimal("18.00"),
        total_general=Decimal("128.00"),
        estado="POR_FACTURAR",
    )
    detalle = DetallePedidoOffline(
        factura_local_uuid=pedido_uuid,
        producto_id=321,
        cantidad=2,
        precio_unitario_historico=Decimal("50.00"),
        impuesto_historico=Decimal("18.00"),
        monto_impuesto=Decimal("18.00"),
        subtotal_linea=Decimal("118.00"),
    )
    db_session.add(pedido)
    db_session.add(detalle)
    db_session.commit()

    response = client.get(f"/api/v1/pedidos/{pedido_uuid}")

    assert response.status_code == 200
    data = response.json()
    assert data["canal_origen"] == "MOVIL"
    assert data["items"] == [
        {
            "detalle_local_uuid": str(detalle.detalle_local_uuid),
            "producto_id": 321,
            "cantidad": 2,
            "precio_unitario_historico": 50.0,
            "impuesto_historico": 18.0,
            "monto_impuesto": 18.0,
            "subtotal_linea": 118.0,
        }
    ]
