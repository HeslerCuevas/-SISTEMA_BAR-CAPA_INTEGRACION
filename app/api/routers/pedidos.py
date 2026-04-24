from typing import List
from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException
from sqlmodel import Session, select
import uuid
import logging
from decimal import Decimal

from app.db.database import get_session
from app.services.sync_service import procesar_pedidos_pendientes
from app.api.deps import get_current_user_payload
from app.schemas.pedidos_schema import PedidoRequest, PedidoResponse
from app.models.integration_models import PedidoOffline, DetallePedidoOffline, DispositivoCliente, MovimientoOffline
from app.clients.core_client import core_client
from app.services.fcm_service import enviar_notificacion_pago

logger = logging.getLogger("RouterPedidos")
router = APIRouter(prefix="/pedidos", tags=["Ventas y Pedidos"])

async def intentar_sincronizar_pedido(pedido_uuid: uuid.UUID, data_pedido: dict):
    from app.db.database import engine

    payload_core = data_pedido.copy()
    payload_core["factura_local_uuid"] = str(pedido_uuid)

    respuesta = await core_client.post("/pedidos/", json=payload_core)

    with Session(engine) as session:
        pedido = session.get(PedidoOffline, pedido_uuid)
        if respuesta and pedido:
            pedido.estado_sincronizacion = "COMPLETADO"
            session.add(pedido)
            session.commit()
            logger.info(f"[IMMEDIATE-SYNC] Pedido {pedido_uuid} marcado como COMPLETADO.")
        elif pedido:
            pedido.ultimo_error = "CORE inalcanzable en intento inmediato."
            session.add(pedido)
            session.commit()

@router.post("/", response_model=PedidoResponse, status_code=201)
async def crear_pedido(
        request: PedidoRequest,
        background_tasks: BackgroundTasks,
        db: Session = Depends(get_session),
        usuario_actual: dict = Depends(get_current_user_payload)
):
    statement = select(PedidoOffline).where(
        PedidoOffline.factura_local_uuid == request.factura_local_uuid
    )
    pedido_existente = db.exec(statement).first()

    if pedido_existente:
        print(f"Reintento detectado. Pedido {request.factura_local_uuid} ya estaba guardado.")
        return {"mensaje": "Pedido ya existía", "factura_local_uuid": str(pedido_existente.factura_local_uuid)}

    nuevo_uuid = request.factura_local_uuid or uuid.uuid4()

    try:
        user_id_raw = usuario_actual.get("sub")
        user_id = int(user_id_raw) if user_id_raw else None
        canal = usuario_actual.get("canal")
    except (ValueError, TypeError):
        raise HTTPException(status_code=401, detail="ID de usuario no válido en el token.")

    empleado_movimiento_id = user_id if canal == "CAJA" and user_id else 1

    try:
        if request.propina_legal == Decimal("0.0") and request.subtotal > Decimal("0.0"):
            request.propina_legal = round(request.subtotal * Decimal("0.10"), 2)

        request.total_general = (
                request.subtotal +
                request.total_impuestos +
                request.propina_legal +
                request.propina_extra
        )

        nuevo_pedido = PedidoOffline(
            factura_local_uuid=nuevo_uuid,
            empleado_id=user_id if canal == "CAJA" else None,
            cliente_id=user_id if canal == "MOVIL" else None,
            canal_origen=canal,
            mesa=request.mesa,
            subtotal=request.subtotal,
            total_impuestos=request.total_impuestos,
            propina_legal=request.propina_legal,
            propina_extra=request.propina_extra,
            total_general=request.total_general,
            estado_sincronizacion="PENDIENTE"
        )
        db.add(nuevo_pedido)

        detalles_para_core = []

        for det in request.detalles:
            d_uuid = det.detalle_local_uuid or uuid.uuid4()

            nuevo_detalle = DetallePedidoOffline(
                detalle_local_uuid=d_uuid,
                factura_local_uuid=nuevo_uuid,
                producto_id=det.producto_id,
                cantidad=det.cantidad,
                precio_unitario_historico=det.precio_unitario,
                impuesto_historico=Decimal("18.0"),
                monto_impuesto=det.monto_impuesto,
                subtotal_linea=det.subtotal_linea
            )
            db.add(nuevo_detalle)

            from app.core.config import settings
            from app.models.integration_models import InventarioLocal
            from datetime import datetime

            inv_local = db.exec(
                select(InventarioLocal).where(
                    InventarioLocal.producto_id == det.producto_id,
                    InventarioLocal.sucursal_id == settings.SUCURSAL_ID
                )
            ).first()

            if inv_local:
                inv_local.cantidad_disponible -= det.cantidad
                inv_local.ultima_sincronizacion = datetime.utcnow()
                db.add(inv_local)

            item_json = det.model_dump(mode='json')
            item_json["detalle_local_uuid"] = str(d_uuid)
            item_json["precio_unitario"] = str(det.precio_unitario)
            item_json["monto_impuesto"] = str(det.monto_impuesto)
            item_json["subtotal_linea"] = str(det.subtotal_linea)
            detalles_para_core.append(item_json)

        db.commit()
        db.refresh(nuevo_pedido)
        logger.info(f"Pedido {nuevo_uuid} y movimientos de inventario guardados en SQLite/Local.")

        return PedidoResponse(
            mensaje="Pedido registrado correctamente en el Gateway.",
            factura_local_uuid=str(nuevo_uuid),
            estado_sincronizacion="PENDIENTE",
            propina_extra=request.propina_extra
        )

    except Exception as e:
        db.rollback()
        logger.error(f"Error DB local: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error interno en DB: {str(e)}")

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
        background_tasks: BackgroundTasks,
        db: Session = Depends(get_session),
        usuario: dict = Depends(get_current_user_payload)
):
    pedido = db.exec(
        select(PedidoOffline).where(PedidoOffline.factura_local_uuid == factura_local_uuid)
    ).first()

    if not pedido:
        raise HTTPException(status_code=404, detail="Pedido no encontrado en el Gateway.")

    if pedido.estado == "FACTURADO":
        return {
            "mensaje": "El pedido ya se encontraba facturado.",
            "sync": pedido.estado_sincronizacion
        }

    pedido.estado = "FACTURADO"
    pedido.estado_sincronizacion = "PENDIENTE"

    db.add(pedido)
    db.commit()
    db.refresh(pedido)

    if pedido.cliente_id:
        dispositivo = db.exec(
            select(DispositivoCliente).where(DispositivoCliente.cliente_id == pedido.cliente_id)
        ).first()

        if dispositivo and dispositivo.fcm_token:
            background_tasks.add_task(
                enviar_notificacion_pago,
                dispositivo.fcm_token,
                str(factura_local_uuid)
            )

    empleado_id = usuario.get("sub")

    try:
        respuesta_core = await core_client.post(
            f"/pedidos/{factura_local_uuid}/facturar",
            json={"empleado_id": int(empleado_id)},
            timeout=5.0
        )

        if respuesta_core and respuesta_core.status_code == 200:
            pedido.estado_sincronizacion = "COMPLETADO"
            db.add(pedido)
            db.commit()

            return {
                "mensaje": "Pedido facturado exitosamente y sincronizado en tiempo real.",
                "sync": "COMPLETADO"
            }

    except Exception as e:
        print(f"[WARNING] Fallo de sincronización con el CORE para pedido {factura_local_uuid}: {e}")

    return {
        "mensaje": "Pedido facturado exitosamente (Modo Offline). El sistema lo enviará a la nube en breve.",
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
        raise HTTPException(status_code=404, detail="Pedido no encontrado en la Capa de Integracion.")

    if pedido.estado_sincronizacion == "CANCELADO":
        return {"mensaje": "El pedido ya estaba cancelado localmente."}

    pedido.estado_sincronizacion = "CANCELADO"
    db.add(pedido)
    db.commit()

    empleado_id = usuario.get("sub")
    try:
        respuesta_core = await core_client.post(
            f"/pedidos/{factura_local_uuid}/cancelar",
            json={"empleado_id": empleado_id, "motivo": "Cancelación desde Capa de Integracion"}
        )

        if respuesta_core:
            pedido.estado_sincronizacion = "COMPLETADO"
            db.add(pedido)
            db.commit()
            return {"mensaje": f"Pedido {factura_local_uuid} cancelado en local y sincronizado con CORE."}

    except Exception as e:
        logger.error(f"Error notificando cancelación al CORE: {e}")

    return {
        "mensaje": "Pedido cancelado localmente. El CORE no respondió, se reintentará la sincronización.",
        "core_notificado": False
    }

@router.get("/pendientes", response_model=List[dict])
async def obtener_pedidos_pendientes_caja(
    db: Session = Depends(get_session)
):
    statement = select(PedidoOffline).where(
        PedidoOffline.estado.in_(["PENDIENTE", "POR_FACTURAR"])
    ).order_by(PedidoOffline.fecha_creacion_local.asc())

    pedidos_pendientes = db.exec(statement).all()

    if not pedidos_pendientes:
        return []

    resultado = []
    for pedido in pedidos_pendientes:
        resultado.append({
            "factura_local_uuid": str(pedido.factura_local_uuid),
            "mesa": pedido.mesa if pedido.mesa else "Para Llevar / Barra",
            "canal_origen": pedido.canal_origen,
            "estado": pedido.estado,
            "subtotal": str(pedido.subtotal),
            "total_impuestos": str(pedido.total_impuestos),
            "total_general": str(pedido.total_general),
            "fecha_creacion": pedido.fecha_creacion_local.strftime('%Y-%m-%d %H:%M')
        })

    return resultado