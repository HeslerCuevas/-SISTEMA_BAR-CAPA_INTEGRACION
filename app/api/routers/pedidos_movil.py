from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Response
from sqlmodel import Session, select
import uuid
from decimal import Decimal
import logging

from app.db.database import get_session
from app.clients.core_client import core_client
from app.models.integration_models import PedidoOffline, DetallePedidoOffline

from app.schemas.pedidos_schema import AgregarItemsRequest, ResumenCuentaResponse, ItemResumen, SolicitarCuentaRequest

logger = logging.getLogger("RouterMovilPedidos")
router = APIRouter(prefix="/clientes/pedidos", tags=["App Móvil - Gestión Dinámica"])


# --- FUNCIONES BACKGROUND ---
async def sync_agregar_items_al_core(factura_local_uuid: uuid.UUID, payload: dict):
    try:
        await core_client.patch(f"/pedidos/{factura_local_uuid}/agregar-items", data=payload)
        logger.info(f"Sincronización exitosa de items adicionales para {factura_local_uuid}")
    except Exception as e:
        logger.error(f"Fallo al sincronizar items con CORE: {e}")


async def sync_estado_pedido_core(factura_local_uuid: uuid.UUID, payload: dict):
    try:
        await core_client.post(f"/pedidos/{factura_local_uuid}/solicitar-cuenta", data=payload)
    except Exception as e:
        logger.error(f"Fallo al notificar cierre al CORE: {e}")


# --- ENDPOINTS MÓVILES ---

@router.patch("/{factura_local_uuid}/agregar-items")
async def agregar_items_local(
        factura_local_uuid: uuid.UUID,
        payload: AgregarItemsRequest,
        background_tasks: BackgroundTasks,
        db: Session = Depends(get_session)
):
    """[OFFLINE-FIRST] Suma bebidas a la cuenta local y avisa al CORE en 2do plano."""
    pedido = db.get(PedidoOffline, factura_local_uuid)

    if not pedido:
        raise HTTPException(status_code=404, detail="Factura local no encontrada")

    try:
        # 1. Actualizar DB Local Inmediatamente
        pedido.subtotal += Decimal(str(payload.nuevo_subtotal_agregado))
        pedido.total_impuestos += Decimal(str(payload.nuevo_impuesto_agregado))
        pedido.propina_legal = pedido.subtotal * Decimal("0.10")
        pedido.total_general = pedido.subtotal + pedido.total_impuestos + pedido.propina_legal + pedido.propina_extra
        pedido.estado_sincronizacion = "PENDIENTE"  # Marcamos para asegurar que se sincronice
        db.add(pedido)

        for item in payload.detalles_adicionales:
            detalle = DetallePedidoOffline(
                detalle_local_uuid=item.detalle_local_uuid,
                factura_local_uuid=factura_local_uuid,
                producto_id=item.producto_id,
                cantidad=item.cantidad,
                precio_unitario_historico=item.precio_unitario,
                impuesto_historico=0.18,
                monto_impuesto=item.monto_impuesto,
                subtotal_linea=item.subtotal_linea
            )
            db.add(detalle)

        db.commit()

        # 2. Enviar actualización al CORE sin bloquear al celular
        background_tasks.add_task(sync_agregar_items_al_core, factura_local_uuid, payload.model_dump(mode='json'))

        return {
            "mensaje": "Items añadidos a la cuenta exitosamente",
            "nuevo_total_general": pedido.total_general
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{factura_local_uuid}/resumen", response_model=ResumenCuentaResponse)
async def resumen_cuenta_local(factura_local_uuid: uuid.UUID, db: Session = Depends(get_session)):
    """[OFFLINE-FIRST] Lee de la caché local para que la App muestre la cuenta al instante."""
    pedido = db.get(PedidoOffline, factura_local_uuid)
    if not pedido:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")

    detalles = db.exec(
        select(DetallePedidoOffline).where(DetallePedidoOffline.factura_local_uuid == factura_local_uuid)).all()

    items_list = [
        ItemResumen(
            producto_nombre=f"Producto {d.producto_id}",
            cantidad=d.cantidad,
            subtotal_linea=d.subtotal_linea,
            estado_preparacion="EN_MESA"
        ) for d in detalles
    ]

    return ResumenCuentaResponse(
        factura_local_uuid=pedido.factura_local_uuid,
        estado_cuenta=pedido.estado_sincronizacion,
        subtotal_acumulado=pedido.subtotal,
        total_impuestos_acumulado=pedido.total_impuestos,
        propina_legal_acumulada=pedido.propina_legal,
        total_general_acumulado=pedido.total_general,
        items_consumidos=items_list
    )


@router.post("/{factura_local_uuid}/solicitar-cuenta")
async def solicitar_cuenta_gateway(
    factura_local_uuid: uuid.UUID,
    payload: SolicitarCuentaRequest,
    db: Session = Depends(get_session)
):
    pedido = db.exec(select(PedidoOffline).where(PedidoOffline.factura_local_uuid == factura_local_uuid)).first()

    if not pedido:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")

    # 1. Guardamos localmente (SQLModel maneja Decimal bien, no hay problema aquí)
    pedido.propina_extra = payload.propina_extra
    pedido.total_general = pedido.subtotal + pedido.total_impuestos + pedido.propina_legal + pedido.propina_extra
    pedido.estado = "POR_FACTURAR"

    db.add(pedido)
    db.commit()

    # 2. Notificamos al CORE
    # --- CAMBIO AQUÍ: Añade mode='json' ---
    payload_para_core = payload.model_dump(mode='json')
    # --------------------------------------

    await core_client.post(
        f"/pedidos/{factura_local_uuid}/solicitar-cuenta",
        data=payload_para_core
    )

    return {"mensaje": "Cuenta solicitada con propina extra aplicada."}