import pytest
import uuid
import concurrent.futures
from decimal import Decimal
from fastapi.testclient import TestClient
from app.models.integration_models import PedidoOffline, DetallePedidoOffline

def test_massive_offline_queue_sync(client: TestClient, db_session):
    """
    Simulate having 100 pending offline orders in the queue and then force a sync.
    """
    # Insert 100 pending orders directly to DB
    for i in range(100):
        pedido = PedidoOffline(
            factura_local_uuid=uuid.uuid4(),
            canal_origen="MOVIL",
            subtotal=Decimal("10.0"),
            total_impuestos=Decimal("1.8"),
            total_general=Decimal("11.8"),
            estado_sincronizacion="PENDIENTE"
        )
        db_session.add(pedido)
    
    db_session.commit()

    # Trigger Sync
    response = client.post("/api/v1/pedidos/forzar-sincronizacion")
    # Even with 100 records, it shouldn't crash. It should spawn a background task or handle them synchronously.
    assert response.status_code in [200, 202]

def test_sync_corrupted_state(client: TestClient, db_session):
    """
    Inject a record with an invalid state to see if the sync job crashes entirely or skips it.
    """
    pedido = PedidoOffline(
        factura_local_uuid=uuid.uuid4(),
        canal_origen="DESCONOCIDO_INVALIDO", # This might break CORE validation
        subtotal=Decimal("-5000.0"), # Negative subtotal
        total_impuestos=Decimal("0.0"),
        total_general=Decimal("-5000.0"),
        estado_sincronizacion="PENDIENTE"
    )
    db_session.add(pedido)
    db_session.commit()

    response = client.post("/api/v1/pedidos/forzar-sincronizacion")
    assert response.status_code in [200, 202]

def test_concurrent_mobile_waiter_calls(client: TestClient):
    """
    Spam the waiter call endpoint concurrently.
    """
    def call_waiter():
        return client.post("/api/v1/movil-mesas/99/llamar-mesero")

    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        results = list(executor.map(lambda _: call_waiter(), range(20)))

    status_codes = [r.status_code for r in results]
    # Mesa 99 doesn't exist, so 404 or 502, but no 500 crash.
    assert all(code in [404, 502, 503, 400] for code in status_codes)
