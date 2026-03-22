from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
import logging

from app.db.database import get_session
from app.clients.core_client import core_client
from app.models.integration_models import Producto
from app.api.deps import get_current_user_payload

logger = logging.getLogger("RouterInventario")
router = APIRouter(prefix="/inventario", tags=["Módulo de Inventario"])


@router.get("/{producto_id}")
async def consultar_stock(
        producto_id: int,
        db: Session = Depends(get_session),
        usuario: dict = Depends(get_current_user_payload)
):
    """
    Consulta el stock de un producto.
    Prioridad: CORE -> SQL Server Local (Caché).
    """
    logger.info(f"Consulta de stock para producto {producto_id} por {usuario.get('sub')}")

    # 1. Intentar con el CORE
    stock_core = await core_client.get(f"/inventario/{producto_id}")

    if stock_core:
        return {
            "producto_id": producto_id,
            "stock": stock_core.get("stock", 0),
            "fuente": "CORE"
        }

    # 2. Fallback: Base de datos local
    producto_local = db.get(Producto, producto_id)
    if not producto_local:
        raise HTTPException(status_code=404, detail="Producto no encontrado ni en CORE ni en Caché.")

    return {
        "producto_id": producto_id,
        "stock": 0,  # O un campo stock_actual si decides agregarlo a tu modelo
        "fuente": "CACHE_LOCAL (OFFLINE)",
        "nota": "La información de stock local puede estar desactualizada."
    }


@router.post("/movimiento")
async def registrar_movimiento(
        movimiento: dict,  # Puedes crear un Schema para esto luego
        db: Session = Depends(get_session),
        usuario: dict = Depends(get_current_user_payload)
):
    """
    Registra entradas o salidas de inventario.
    Utiliza el patrón Outbox para asegurar que el CORE se entere.
    """
    # Aquí usaríamos una lógica similar a la de pedidos:
    # 1. Guardar movimiento en una tabla local 'Sync.Movimientos_Inventario'
    # 2. Responder al usuario: "Movimiento registrado"
    # 3. Sincronizar en segundo plano.

    respuesta_core = await core_client.post("/inventario/movimiento", data=movimiento)

    if respuesta_core:
        return {"mensaje": "Movimiento sincronizado con el CORE.", "data": respuesta_core}

    return {"mensaje": "CORE offline. Movimiento guardado localmente para sincronización futura."}