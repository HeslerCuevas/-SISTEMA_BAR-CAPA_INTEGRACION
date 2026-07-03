from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from sqlalchemy import func
import logging
import uuid
from datetime import datetime
from app.core.timezone import get_local_now

from app.db.database import get_session
from app.clients.core_client import core_client
from app.models.integration_models import MovimientoOffline, InventarioLocal, DetallePedidoOffline, PedidoOffline
from app.api.deps import get_current_user_payload
from app.schemas.inventario_schemas import MovimientoCreate
from app.core.config import settings

logger = logging.getLogger("RouterInventario")
router = APIRouter(prefix="/inventario", tags=["Módulo de Inventario"])


@router.get("/{producto_id}")
async def consultar_stock(
        producto_id: int,
        db: Session = Depends(get_session),
        usuario: dict = Depends(get_current_user_payload)
):
    logger.info(f"Consulta de stock para producto {producto_id} por {usuario.get('sub')}")

    stock_core = await core_client.get(f"/api/v1/inventario/{producto_id}")

    if stock_core:
        core_stock = int(stock_core.get("cantidad_disponible", 0))

        # ── Stock Race-Condition Fix ────────────────────────────────────────────────────
        # CORE's stock is authoritative, but it doesn't yet know about orders
        # that CAJA_NEW has processed locally but haven't been synced yet.
        # Subtract pending deductions so CAJA doesn't over-sell.
        pending_result = db.exec(
            select(func.sum(DetallePedidoOffline.cantidad))
            .select_from(DetallePedidoOffline)
            .join(
                PedidoOffline,
                DetallePedidoOffline.factura_local_uuid == PedidoOffline.factura_local_uuid
            )
            .where(
                DetallePedidoOffline.producto_id == producto_id,
                ~PedidoOffline.estado_sincronizacion.in_(["COMPLETADO", "CANCELADO"])
            )
        ).first()

        pending_deductions = int(pending_result) if pending_result is not None else 0
        adjusted_stock = max(0, core_stock - pending_deductions)

        return {
            "producto_id": producto_id,
            "stock": adjusted_stock,
            "fuente": "CORE" if pending_deductions == 0 else "CORE_AJUSTADO_LOCAL",
            "descuento_pendiente": pending_deductions
        }

    inv_local = db.exec(
        select(InventarioLocal).where(
            InventarioLocal.producto_id == producto_id,
            InventarioLocal.sucursal_id == settings.SUCURSAL_ID
        )
    ).first()

    if not inv_local:
        raise HTTPException(status_code=404, detail="Producto sin registro de inventario local.")

    return {
        "producto_id": producto_id,
        "stock": inv_local.cantidad_disponible,
        "fuente": "CACHE_LOCAL (OFFLINE)",
        "ultima_sincronizacion": inv_local.ultima_sincronizacion
    }


@router.post("/movimiento")
async def registrar_movimiento(
        movimiento: MovimientoCreate,
        db: Session = Depends(get_session),
        usuario: dict = Depends(get_current_user_payload)
):
    empleado_id = int(usuario.get("sub", 1))

    try:
        nuevo_movimiento = MovimientoOffline(
            id=uuid.uuid4(),
            empleado_id=empleado_id,
            tipo_movimiento=movimiento.tipo_movimiento,
            producto_id=movimiento.producto_id,
            cantidad=movimiento.cantidad,
            motivo=movimiento.motivo,
            estado_sincronizacion="PENDIENTE",
            fecha_creacion_local=get_local_now()
        )
        db.add(nuevo_movimiento)

        inv_local = db.exec(
            select(InventarioLocal).where(
                InventarioLocal.producto_id == movimiento.producto_id,
                InventarioLocal.sucursal_id == settings.SUCURSAL_ID
            )
        ).first()

        if inv_local:
            if movimiento.tipo_movimiento == "ENTRADA":
                inv_local.cantidad_disponible += movimiento.cantidad
            elif movimiento.tipo_movimiento == "SALIDA":
                inv_local.cantidad_disponible -= movimiento.cantidad

            inv_local.ultima_sincronizacion = get_local_now()
            db.add(inv_local)
        else:
            nuevo_inv = InventarioLocal(
                producto_id=movimiento.producto_id,
                sucursal_id=settings.SUCURSAL_ID,
                cantidad_disponible=movimiento.cantidad if movimiento.tipo_movimiento == "ENTRADA" else 0,
                ultima_sincronizacion=get_local_now()
            )
            db.add(nuevo_inv)

        db.commit()
        db.refresh(nuevo_movimiento)

        payload_core = {
            "producto_id": movimiento.producto_id,
            "empleado_id": empleado_id,
            "tipo_movimiento": movimiento.tipo_movimiento,
            "cantidad": movimiento.cantidad,
            "motivo": movimiento.motivo,
            "movimiento_local_uuid": str(nuevo_movimiento.id)
        }

        respuesta_core = await core_client.post("/api/v1/inventario/movimiento", json=payload_core)

        if respuesta_core:
            nuevo_movimiento.estado_sincronizacion = "COMPLETADO"
            db.add(nuevo_movimiento)
            db.commit()
            return {
                "status": "success",
                "mensaje": "Movimiento registrado y sincronizado",
                "stock_local_actual": inv_local.cantidad_disponible if inv_local else movimiento.cantidad
            }

        return {
            "status": "warning",
            "mensaje": "Sin conexión al CORE. Stock actualizado localmente y movimiento en cola."
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Error en registro de movimiento: {str(e)}")
        raise HTTPException(status_code=500, detail="Error interno al procesar el inventario.")