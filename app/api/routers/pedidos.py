from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException
from sqlmodel import Session, select
import uuid
import logging

from app.db.database import get_session
from app.services.sync_service import procesar_pedidos_pendientes
from app.api.deps import get_current_user_payload
from app.schemas.pedidos_schema import PedidoRequest, PedidoResponse
from app.models.integration_models import PedidoOffline, DetallePedidoOffline, DispositivoCliente
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
    nuevo_uuid = request.factura_local_uuid or uuid.uuid4()

    # 1. Extraer ID del usuario (JWT sub es string, DB es INT)
    try:
        user_id_raw = usuario_actual.get("sub")
        user_id = int(user_id_raw) if user_id_raw else None
        canal = usuario_actual.get("canal")
    except (ValueError, TypeError):
        raise HTTPException(status_code=401, detail="ID de usuario no válido en el token.")

    # 2. Guardado en Base de Datos Local
    try:
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

        # --- ARREGLO CRÍTICO: Sincronización de UUIDs de Detalles ---
        detalles_para_core = []

        for det in request.detalles:
            # 1. Determinamos el UUID (Prioridad: Flutter > Nuevo generado aquí)
            d_uuid = det.detalle_local_uuid or uuid.uuid4()

            # 2. Creamos el objeto para la DB local de Integración
            nuevo_detalle = DetallePedidoOffline(
                detalle_local_uuid=d_uuid,
                factura_local_uuid=nuevo_uuid,
                producto_id=det.producto_id,
                cantidad=det.cantidad,
                precio_unitario_historico=det.precio_unitario,
                impuesto_historico=18.0,
                monto_impuesto=det.monto_impuesto,
                subtotal_linea=det.subtotal_linea
            )
            db.add(nuevo_detalle)

            # 3. Preparamos el ítem para el payload del CORE asegurando el UUID
            item_json = det.model_dump(mode='json')  # mode='json' limpia Decimals/UUIDs
            item_json["detalle_local_uuid"] = str(d_uuid)
            detalles_para_core.append(item_json)

        db.commit()
        logger.info(f"✅ Pedido {nuevo_uuid} guardado en Sync.Pedidos_Offline.")

    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error DB local: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error interno en DB: {str(e)}")

    # 3. Preparar sincronización al CORE (Background Task)
    # Dump general en modo JSON para limpiar el resto de campos (Decimal, UUID cabecera)
    datos_para_core = request.model_dump(mode='json')

    # Sobrescribimos la lista de detalles con la que YA TIENE los UUIDs inyectados
    datos_para_core["detalles"] = detalles_para_core

    # Inyectamos metadatos del usuario actual
    datos_para_core["canal_origen"] = canal
    datos_para_core["cliente_id"] = nuevo_pedido.cliente_id
    datos_para_core["empleado_id"] = nuevo_pedido.empleado_id
    datos_para_core["propina_extra"] = float(nuevo_pedido.propina_extra)

    background_tasks.add_task(intentar_sincronizar_pedido, nuevo_uuid, datos_para_core)

    # 4. RETORNO
    return PedidoResponse(
        mensaje="Pedido registrado correctamente en el Gateway.",
        factura_local_uuid=str(nuevo_uuid),
        estado_sincronizacion="PENDIENTE",
        propina_extra=request.propina_extra
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


# Asegúrate de tener importado DispositivoCliente y enviar_notificacion_pago

@router.post("/{factura_local_uuid}/facturar")
async def facturar_pedido(
        factura_local_uuid: uuid.UUID,
        background_tasks: BackgroundTasks,
        db: Session = Depends(get_session),
        usuario: dict = Depends(get_current_user_payload)
):
    pedido = db.exec(select(PedidoOffline).where(PedidoOffline.factura_local_uuid == factura_local_uuid)).first()

    if not pedido:
        raise HTTPException(status_code=404, detail="Pedido no encontrado en el Gateway.")

    if pedido.estado == "FACTURADO":
        return {"mensaje": "El pedido ya se encontraba facturado.", "sync": pedido.estado_sincronizacion}

    # Marcamos como facturado localmente
    pedido.estado = "FACTURADO"
    pedido.estado_sincronizacion = "PENDIENTE"

    db.add(pedido)
    db.commit()

    # Obtenemos el ID del empleado que está usando la caja
    empleado_id = usuario.get("sub")

    # 🚨 EL CAMBIO CRÍTICO: Usamos 'json=' para mandar un payload limpio
    respuesta_core = await core_client.post(
        f"/pedidos/{factura_local_uuid}/facturar",
        json={"empleado_id": int(empleado_id)}
    )

    if respuesta_core:
        # Si el CORE responde exitosamente, actualizamos la sincronización
        pedido.estado_sincronizacion = "COMPLETADO"
        db.add(pedido)
        db.commit()

        # === Lógica de Notificaciones Push (FCM) ===
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

        return {
            "mensaje": f"Pedido {factura_local_uuid} facturado y sincronizado.",
            "sync": "COMPLETADO"
        }

    # Si respuesta_core es None (porque falló la red o dio timeout), cae aquí
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