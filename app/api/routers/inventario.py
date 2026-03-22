from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session
import logging

from app.db.database import get_session
from app.clients.core_client import core_client
from app.models.integration_models import Producto, MovimientoOffline
from app.api.deps import get_current_user_payload
from app.schemas.inventario_schemas import MovimientoCreate

logger = logging.getLogger("RouterInventario")
router = APIRouter(prefix="/inventario", tags=["Módulo de Inventario"])


@router.get("/{producto_id}")
async def consultar_stock(
        producto_id: int,
        db: Session = Depends(get_session),
        usuario: dict = Depends(get_current_user_payload)
):
    logger.info(f"Consulta de stock para producto {producto_id} por {usuario.get('sub')}")

    stock_core = await core_client.get(f"/inventario/{producto_id}")

    if stock_core:
        return {
            "producto_id": producto_id,
            "stock": stock_core.get("stock", 0),
            "fuente": "CORE"
        }

    producto_local = db.get(Producto, producto_id)
    if not producto_local:
        raise HTTPException(status_code=404, detail="Producto no encontrado ni en CORE ni en Caché.")

    return {
        "producto_id": producto_id,
        "stock": 0,
        "fuente": "CACHE_LOCAL (OFFLINE)",
        "nota": "La información de stock local puede estar desactualizada."
    }


@router.post("/movimiento")
async def registrar_movimiento(
        movimiento: MovimientoCreate,
        db: Session = Depends(get_session),
        usuario: dict = Depends(get_current_user_payload)
):
    empleado_id = int(usuario.get("sub", 1))

    nuevo_movimiento = MovimientoOffline(
        empleado_id=empleado_id,
        tipo_movimiento=movimiento.tipo_movimiento,
        producto_id=movimiento.producto_id,
        cantidad=movimiento.cantidad,
        motivo=movimiento.motivo,
        estado_sincronizacion="PENDIENTE"
    )
    db.add(nuevo_movimiento)
    db.commit()
    db.refresh(nuevo_movimiento)

    payload_core = {
        "producto_id": movimiento.producto_id,
        "empleado_id": empleado_id,
        "tipo_movimiento": movimiento.tipo_movimiento,
        "cantidad": movimiento.cantidad,
        "motivo": movimiento.motivo
    }

    respuesta_core = await core_client.post("/inventario/movimiento", data=payload_core)

    if respuesta_core:
        nuevo_movimiento.estado_sincronizacion = "COMPLETADO"
        db.add(nuevo_movimiento)
        db.commit()

        return {
            "status": "success",
            "mensaje": "Movimiento registrado y sincronizado",
            "data": respuesta_core
        }

    return {
        "status": "warning",
        "mensaje": "Sin conexión al CORE. Movimiento asegurado localmente."
    }