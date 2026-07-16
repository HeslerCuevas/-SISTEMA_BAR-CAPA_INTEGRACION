from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
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


async def sync_agregar_items_al_core(factura_local_uuid: uuid.UUID, payload: dict):
    try:
        await core_client.patch(f"/api/v1/pedidos/{factura_local_uuid}/agregar-items", json=payload)
        logger.info(f"Successful synchronization of additional items for {factura_local_uuid}")
    except Exception as e:
        logger.error(f"Failed to synchronize items with CORE: {e}")


async def sync_estado_pedido_core(factura_local_uuid: uuid.UUID, payload: dict):
    try:
        await core_client.post(f"/api/v1/pedidos/{factura_local_uuid}/solicitar-cuenta", json=payload)
    except Exception as e:
        logger.error(f"Failed to notify CORE of closure: {e}")



@router.patch("/{factura_local_uuid}/agregar-items")
async def agregar_items_local(
        factura_local_uuid: uuid.UUID,
        payload: AgregarItemsRequest,
        background_tasks: BackgroundTasks,
        db: Session = Depends(get_session)
):
    pedido = db.get(PedidoOffline, factura_local_uuid)

    if not pedido:
        raise HTTPException(status_code=404, detail="Local invoice not found")

    try:
        pedido.subtotal += Decimal(str(payload.nuevo_subtotal_agregado))
        pedido.total_impuestos += Decimal(str(payload.nuevo_impuesto_agregado))
        pedido.propina_legal = pedido.subtotal * Decimal("0.10")
        pedido.total_general = pedido.subtotal + pedido.total_impuestos + pedido.propina_legal + pedido.propina_extra
        pedido.estado_sincronizacion = "PENDIENTE"
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
    pedido = db.get(PedidoOffline, factura_local_uuid)
    if not pedido:
        raise HTTPException(status_code=404, detail="Order not found")

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
        propina_extra_acumulada=pedido.propina_extra,
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
        raise HTTPException(status_code=404, detail="Order not found")

    pedido.propina_extra = payload.propina_extra
    pedido.total_general = pedido.subtotal + pedido.total_impuestos + pedido.propina_legal + pedido.propina_extra
    pedido.estado = "POR_FACTURAR"

    db.add(pedido)
    db.commit()

    payload_para_core = payload.model_dump(mode='json')

    await core_client.post(
        f"/api/v1/pedidos/{factura_local_uuid}/solicitar-cuenta",
        json=payload_para_core
    )

    return {"mensaje": "Cuenta solicitada con propina extra aplicada."}
