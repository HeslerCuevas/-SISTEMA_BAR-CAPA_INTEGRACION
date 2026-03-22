from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException
from sqlmodel import Session, select
import uuid
import logging

from app.db.database import get_session
from app.services.sync_service import procesar_pedidos_pendientes
from app.api.deps import get_current_user_payload
from app.schemas.pedidos_schema import PedidoRequest, PedidoResponse
from app.models.integration_models import PedidoOffline, DetallePedidoOffline
from app.clients.core_client import core_client

logger = logging.getLogger("RouterPedidos")
router = APIRouter(prefix="/pedidos", tags=["Ventas y Pedidos"])


async def intentar_sincronizar_pedido(pedido_uuid: uuid.UUID, data_pedido: dict):
    logger.info(f"[BACKGROUND] Intentando subir pedido {pedido_uuid} al CORE...")

    payload_core = data_pedido.copy()
    payload_core["integracion_uuid"] = str(pedido_uuid)

    respuesta = await core_client.post("/pedidos/", data=payload_core)

    if respuesta:
        logger.info(f"[BACKGROUND] Pedido {pedido_uuid} sincronizado con éxito.")
    else:
        logger.warning(f"[BACKGROUND] CORE inalcanzable. Pedido {pedido_uuid} encolado para reintento.")


@router.post("/", response_model=PedidoResponse, status_code=201)
async def crear_pedido(
        request: PedidoRequest,
        background_tasks: BackgroundTasks,
        db: Session = Depends(get_session),
        usuario_actual: dict = Depends(get_current_user_payload)
):

    nuevo_uuid = uuid.uuid4()

    try:
        nuevo_pedido = PedidoOffline(
            factura_local_uuid=nuevo_uuid,
            empleado_id=usuario_actual.get("sub") if usuario_actual.get("canal") == "CAJA" else None,
            cliente_id=usuario_actual.get("sub") if usuario_actual.get("canal") == "MOVIL" else None,
            canal_origen=usuario_actual.get("canal"),
            mesa=request.mesa,
            subtotal=request.subtotal,
            total_impuestos=request.total_impuestos,
            propina_legal=request.propina_legal,
            total_general=request.total_general,
            estado_sincronizacion="PENDIENTE"
        )
        db.add(nuevo_pedido)

        for det in request.detalles:
            nuevo_detalle = DetallePedidoOffline(
                factura_local_uuid=nuevo_uuid,
                producto_id=det.producto_id,
                cantidad=det.cantidad,
                precio_unitario_historico=det.precio_unitario,
                impuesto_historico=0,
                monto_impuesto=det.monto_impuesto,
                subtotal_linea=det.subtotal_linea
            )
            db.add(nuevo_detalle)

        db.commit()
        logger.info(f"Pedido {nuevo_uuid} guardado en Cache Local.")

    except Exception as e:
        db.rollback()
        logger.critical(f"Error guardando pedido localmente: {e}")
        raise HTTPException(status_code=500, detail="Error crítico guardando la orden localmente.")

    background_tasks.add_task(intentar_sincronizar_pedido, nuevo_uuid, request.model_dump())

    return PedidoResponse(
        mensaje="Pedido registrado correctamente en el Gateway.",
        factura_local_uuid=str(nuevo_uuid),
        estado_sincronizacion="PENDIENTE"
    )


@router.post("/forzar-sincronizacion")
async def forzar_sincronizacion_offline(
    db: Session = Depends(get_session),
    usuario_actual: dict = Depends(get_current_user_payload)
):
    if usuario_actual.get("canal") != "CAJA":
        raise HTTPException(
            status_code=403,
            detail="Operación no permitida. Solo disponible en terminales de Caja."
        )

    exitosos, fallidos = await procesar_pedidos_pendientes(db)

    return {
        "mensaje": "Proceso de sincronización finalizado.",
        "resultados": {
            "exitosos": exitosos,
            "fallidos": fallidos,
            "total_procesados": exitosos + fallidos
        }
    }


@router.post("/{factura_local_uuid}/facturar")
async def facturar_pedido(
        factura_local_uuid: uuid.UUID,
        db: Session = Depends(get_session),
        usuario: dict = Depends(get_current_user_payload)
):
    pedido = db.exec(select(PedidoOffline).where(PedidoOffline.factura_local_uuid == factura_local_uuid)).first()

    if not pedido:
        raise HTTPException(status_code=404, detail="Pedido no encontrado en el Gateway.")

    if pedido.estado == "FACTURADO":
        return {"mensaje": "El pedido ya se encontraba facturado.", "sync": pedido.estado_sincronizacion}

    pedido.estado = "FACTURADO"
    pedido.estado_sincronizacion = "PENDIENTE"

    db.add(pedido)
    db.commit()

    empleado_id = usuario.get("sub")
    respuesta_core = await core_client.post(
        f"/pedidos/{factura_local_uuid}/facturar",
        data={"empleado_id": empleado_id}
    )

    if respuesta_core:
        pedido.estado_sincronizacion = "COMPLETADO"
        db.add(pedido)
        db.commit()
        return {
            "mensaje": f"Pedido {factura_local_uuid} facturado y sincronizado.",
            "sync": "COMPLETADO"
        }

    return {
        "mensaje": "CORE offline. Pedido facturado localmente. Se sincronizará en breve.",
        "sync": "PENDIENTE"
    }


@router.post("/{factura_local_uuid}/cancelar")
async def cancelar_pedido(
        factura_local_uuid: uuid.UUID,
        db: Session = Depends(get_session),
        usuario: dict = Depends(get_current_user_payload)
):
    pedido = db.exec(select(PedidoOffline).where(PedidoOffline.factura_local_uuid == factura_local_uuid)).first()

    if not pedido:
        raise HTTPException(status_code=404, detail="Pedido no encontrado en el Gateway.")

    if pedido.estado == "CANCELADO":
        return {"mensaje": "El pedido ya estaba cancelado."}

    pedido.estado = "CANCELADO"
    pedido.estado_sincronizacion = "PENDIENTE"

    db.add(pedido)
    db.commit()

    empleado_id = usuario.get("sub")
    respuesta_core = await core_client.post(
        f"/pedidos/{factura_local_uuid}/cancelar",
        data={"empleado_id": empleado_id}
    )

    if respuesta_core:
        pedido.estado_sincronizacion = "COMPLETADO"
        db.add(pedido)
        db.commit()
        return {"mensaje": f"Pedido {factura_local_uuid} cancelado con éxito.", "core_notificado": True}

    return {"mensaje": "Pedido cancelado localmente. CORE offline.", "core_notificado": False}