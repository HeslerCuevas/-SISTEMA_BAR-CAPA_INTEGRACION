from typing import List
from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException
from sqlmodel import Session, select
import uuid
import logging
from decimal import Decimal

from app.db.database import get_session
from app.services.sync_service import procesar_pedidos_pendientes
from app.api.deps import get_current_user_payload
from app.schemas.pedidos_schema import (
    PedidoRequest, PedidoResponse,
    AgregarItemsRequest, SolicitarCuentaRequest,
    ItemResumen, ResumenCuentaResponse
)
from app.models.integration_models import PedidoOffline, DetallePedidoOffline, DispositivoCliente, MovimientoOffline
from app.clients.core_client import core_client
from app.services.fcm_service import enviar_notificacion_pago

logger = logging.getLogger("RouterPedidos")
router = APIRouter(prefix="/pedidos", tags=["Ventas y Pedidos"])


# ─── Helper: push a PedidoOffline to CORE ─────────────────────────────────────

async def _push_pedido_to_core(pedido: PedidoOffline, db: Session) -> bool:
    """Build a CORE-compatible PedidoCreate payload and POST it to CORE.
    Marks pedido.estado_sincronizacion = 'COMPLETADO' and adds to session on success
    but does NOT commit — the caller is responsible for committing.
    Returns True on success, False otherwise.
    """
    try:
        detalles = db.exec(
            select(DetallePedidoOffline).where(
                DetallePedidoOffline.factura_local_uuid == pedido.factura_local_uuid
            )
        ).all()

        # Validate canal — CORE only accepts these three literals
        canal = pedido.canal_origen if pedido.canal_origen in ("CAJA", "MOVIL", "WEB") else "CAJA"

        payload_core = {
            "empleado_id": pedido.empleado_id,
            "cliente_id": pedido.cliente_id,
            "canal_origen": canal,
            "mesa": pedido.mesa,
            "propina_extra": float(pedido.propina_extra) if pedido.propina_extra else 0.0,
            "factura_local_uuid": str(pedido.factura_local_uuid),
            "detalles": [
                {
                    "producto_id": d.producto_id,
                    "cantidad": d.cantidad,
                    "detalle_local_uuid": str(d.detalle_local_uuid)
                }
                for d in detalles
            ]
        }

        respuesta = await core_client.post("/api/v1/pedidos/", json=payload_core)

        # CORE returns the created order or a duplicate-detection message — both are OK
        if respuesta is not None and "detail" not in respuesta:
            pedido.estado_sincronizacion = "COMPLETADO"
            db.add(pedido)
            logger.info(f"[PUSH-CORE] Order {pedido.factura_local_uuid} accepted by CORE.")
            return True

        logger.warning(f"[PUSH-CORE] CORE rejected order {pedido.factura_local_uuid}: {respuesta}")
        return False

    except Exception as exc:
        logger.error(f"[PUSH-CORE] Error sending {pedido.factura_local_uuid} to CORE: {exc}")
        return False

async def intentar_sincronizar_pedido(pedido_uuid: uuid.UUID, data_pedido: dict):
    from app.db.database import engine

    payload_core = data_pedido.copy()
    payload_core["factura_local_uuid"] = str(pedido_uuid)

    respuesta = await core_client.post("/api/v1/pedidos/", json=payload_core)

    with Session(engine) as session:
        pedido = session.get(PedidoOffline, pedido_uuid)
        if respuesta and pedido:
            pedido.estado_sincronizacion = "COMPLETADO"
            session.add(pedido)
            session.commit()
            logger.info(f"[IMMEDIATE-SYNC] Order {pedido_uuid} marked as COMPLETED.")
        elif pedido:
            pedido.ultimo_error = "CORE unreachable during immediate attempt."
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
        print(f"Retry detected. Order {request.factura_local_uuid} was already saved.")
        return {"mensaje": "Pedido ya existía", "factura_local_uuid": str(pedido_existente.factura_local_uuid)}

    nuevo_uuid = request.factura_local_uuid or uuid.uuid4()

    try:
        user_id_raw = usuario_actual.get("sub")
        user_id = int(user_id_raw) if user_id_raw else None
        canal = usuario_actual.get("canal")
    except (ValueError, TypeError):
        raise HTTPException(status_code=401, detail="User ID is invalid in the token.")

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
            from app.core.timezone import get_local_now

            inv_local = db.exec(
                select(InventarioLocal).where(
                    InventarioLocal.producto_id == det.producto_id,
                    InventarioLocal.sucursal_id == settings.SUCURSAL_ID
                )
            ).first()

            if inv_local:
                inv_local.cantidad_disponible -= det.cantidad
                inv_local.ultima_sincronizacion = get_local_now()
                db.add(inv_local)

            item_json = det.model_dump(mode='json')
            item_json["detalle_local_uuid"] = str(d_uuid)
            item_json["precio_unitario"] = str(det.precio_unitario)
            item_json["monto_impuesto"] = str(det.monto_impuesto)
            item_json["subtotal_linea"] = str(det.subtotal_linea)
            detalles_para_core.append(item_json)

        db.commit()
        db.refresh(nuevo_pedido)
        logger.info(f"Order {nuevo_uuid} saved locally. Attempting immediate synchronization with CORE...")

        # ── Inline CORE sync: push immediately so /facturar can bill right away ──
        # Build CORE payload from the already-stored detail UUIDs (detalles_para_core)
        try:
            core_detalles = [
                {
                    "producto_id": d["producto_id"],
                    "cantidad": d["cantidad"],
                    "detalle_local_uuid": d["detalle_local_uuid"]
                }
                for d in detalles_para_core
            ]
            canal_core = canal if canal in ("CAJA", "MOVIL", "WEB") else "CAJA"
            payload_core = {
                "empleado_id": nuevo_pedido.empleado_id,
                "cliente_id": nuevo_pedido.cliente_id,
                "canal_origen": canal_core,
                "mesa": nuevo_pedido.mesa,
                "propina_extra": float(nuevo_pedido.propina_extra),
                "factura_local_uuid": str(nuevo_uuid),
                "detalles": core_detalles
            }
            respuesta_core = await core_client.post("/api/v1/pedidos/", json=payload_core)
            if respuesta_core is not None and "detail" not in respuesta_core:
                nuevo_pedido.estado_sincronizacion = "COMPLETADO"
                estado_actual = "COMPLETADO"  # capture before commit expires the object
                db.add(nuevo_pedido)
                db.commit()
                logger.info(f"[IMMEDIATE] Order {nuevo_uuid} synchronized with CORE successfully.")
            else:
                estado_actual = "PENDIENTE"
                logger.warning(f"[IMMEDIATE] CORE did not accept {nuevo_uuid}: {respuesta_core}. It will be queued.")
        except Exception as sync_exc:
            estado_actual = "PENDIENTE"
            logger.warning(f"[IMMEDIATE] Could not synchronize {nuevo_uuid} with CORE: {sync_exc}. It will be queued.")

        return PedidoResponse(
            mensaje="Order registered successfully in the Gateway.",
            factura_local_uuid=str(nuevo_uuid),
            estado_sincronizacion=estado_actual,
            propina_extra=request.propina_extra
        )

    except Exception as e:
        db.rollback()
        logger.error(f"Local DB error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal DB error: {str(e)}")

@router.post("/forzar-sincronizacion")
async def forzar_sincronizacion_offline(
    db: Session = Depends(get_session),
    usuario_actual: dict = Depends(get_current_user_payload)
):
    if usuario_actual.get("canal") != "CAJA":
        raise HTTPException(
            status_code=403,
            detail="Operation not allowed. Available only on cash-register terminals."
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
        raise HTTPException(status_code=404, detail="Order not found in the Gateway.")

    if pedido.estado == "FACTURADO":
        return {
            "mensaje": "El pedido ya se encontraba facturado.",
            "sync": pedido.estado_sincronizacion
        }

    pedido.estado = "FACTURADO"
    # Preserve COMPLETADO state if the order was already pushed to CORE by crear_pedido's inline sync.
    # Only mark PENDIENTE if we haven't synced yet.
    if pedido.estado_sincronizacion not in ("COMPLETADO",):
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
    if not empleado_id:
        # Token missing sub — bill locally and queue for later sync
        logger.warning(f"[FACTURAR] Token sin 'sub' para pedido {factura_local_uuid}. Modo offline.")
        return {
            "mensaje": "Pedido facturado localmente. Token sin empleado_id válido, se reintentará la sincronización.",
            "sync": "PENDIENTE"
        }

    try:
        empleado_id_int = int(empleado_id)

        # ── Step 1: ensure the order exists in CORE before trying to bill it ──
        # Without this, CORE returns 404 when /facturar is called immediately
        # after POST /pedidos/ because the background sync hasn't run yet.
        if pedido.estado_sincronizacion != "COMPLETADO":
            logger.info(f"[INVOICE] Order {factura_local_uuid} is not yet in CORE. Sending now...")
            pushed = await _push_pedido_to_core(pedido, db)
            if not pushed:
                logger.warning(f"[INVOICE] Could not send {factura_local_uuid} to CORE. Offline mode.")
                return {
                    "mensaje": "Pedido facturado localmente. El CORE no está disponible, se reintentará.",
                    "sync": "PENDIENTE"
                }
            db.commit()  # persist COMPLETADO state before calling /facturar

        # ── Step 2: bill the order in CORE ──────────────────────────────────
        respuesta_core = await core_client.post(
            f"/api/v1/pedidos/{factura_local_uuid}/facturar",
            json={"empleado_id": empleado_id_int},
        )

        if respuesta_core is not None and "detail" not in respuesta_core:
            pedido.estado_sincronizacion = "COMPLETADO"
            db.add(pedido)
            db.commit()

            return {
                "mensaje": "Pedido facturado exitosamente y sincronizado en tiempo real.",
                "sync": "COMPLETADO"
            }

        error_detail = respuesta_core.get("detail", "Respuesta inesperada") if respuesta_core else "CORE no respondió"
        logger.error(f"[INVOICE] CORE rejected /facturar for {factura_local_uuid}: {error_detail}")

    except Exception as e:
        logger.warning(f"[INVOICE] Synchronization failed with CORE for {factura_local_uuid}: {e}")

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
        raise HTTPException(status_code=404, detail="Order not found in the Integration Layer.")

    if pedido.estado_sincronizacion == "CANCELADO":
        return {"mensaje": "El pedido ya estaba cancelado localmente."}

    pedido.estado_sincronizacion = "CANCELADO"
    db.add(pedido)
    db.commit()

    empleado_id = usuario.get("sub")
    try:
        respuesta_core = await core_client.post(
            f"/api/v1/pedidos/{factura_local_uuid}/cancelar",
            json={"empleado_id": empleado_id, "motivo": "Cancelación desde Capa de Integracion"}
        )

        if respuesta_core:
            pedido.estado_sincronizacion = "COMPLETADO"
            db.add(pedido)
            db.commit()
            return {"mensaje": f"Pedido {factura_local_uuid} cancelado en local y sincronizado con CORE."}

    except Exception as e:
        logger.error(f"Error notifying CORE of cancellation: {e}")

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
            "propina_legal": str(pedido.propina_legal),
            "propina_extra": str(pedido.propina_extra),
            "total_general": str(pedido.total_general),
            "fecha_creacion": pedido.fecha_creacion_local.strftime('%Y-%m-%d %H:%M')
        })

    return resultado


@router.get("/{factura_local_uuid}")
async def obtener_detalle_pedido_para_caja(
        factura_local_uuid: uuid.UUID,
        db: Session = Depends(get_session)
):
    """Return a remote order and its line items for CAJA's Active Tables flow."""
    pedido = db.get(PedidoOffline, factura_local_uuid)
    if not pedido:
        raise HTTPException(status_code=404, detail="Order not found.")

    detalles = db.exec(
        select(DetallePedidoOffline).where(
            DetallePedidoOffline.factura_local_uuid == factura_local_uuid
        )
    ).all()

    return {
        "factura_local_uuid": str(pedido.factura_local_uuid),
        "mesa": pedido.mesa,
        "canal_origen": pedido.canal_origen,
        "estado": pedido.estado,
        "items": [
            {
                "detalle_local_uuid": str(detalle.detalle_local_uuid),
                "producto_id": detalle.producto_id,
                "cantidad": detalle.cantidad,
                "precio_unitario_historico": detalle.precio_unitario_historico,
                "impuesto_historico": detalle.impuesto_historico,
                "monto_impuesto": detalle.monto_impuesto,
                "subtotal_linea": detalle.subtotal_linea,
            }
            for detalle in detalles
        ],
    }


# ─── Resumen de cuenta (con fallback local) ───────────────────────────────────

@router.get("/{factura_local_uuid}/resumen", response_model=ResumenCuentaResponse)
async def resumen_cuenta(
        factura_local_uuid: uuid.UUID,
        db: Session = Depends(get_session)
):
    """Returns the current tab for a given order. Tries CORE first, falls back to local cache."""
    core_data = await core_client.get(f"/api/v1/pedidos/{factura_local_uuid}/resumen")
    if core_data and "detail" not in core_data:
        return core_data

    # Fallback: build resumen from local tables
    pedido = db.get(PedidoOffline, factura_local_uuid)
    if not pedido:
        raise HTTPException(status_code=404, detail="Order not found.")

    detalles = db.exec(
        select(DetallePedidoOffline).where(DetallePedidoOffline.factura_local_uuid == factura_local_uuid)
    ).all()

    items_list = [
        ItemResumen(
            producto_nombre=f"Producto #{d.producto_id}",
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
        propina_extra_acumulada=pedido.propina_extra,
        total_general_acumulado=pedido.total_general,
        items_consumidos=items_list
    )


# ─── Agregar items (local-first, CORE synced in background) ───────────────────

@router.patch("/{factura_local_uuid}/agregar-items")
async def agregar_items(
        factura_local_uuid: uuid.UUID,
        payload: AgregarItemsRequest,
        background_tasks: BackgroundTasks,
        db: Session = Depends(get_session)
):
    """Adds items to an existing order. Writes locally first for POS/offline resilience, then syncs CORE."""
    pedido = db.get(PedidoOffline, factura_local_uuid)
    if not pedido:
        raise HTTPException(status_code=404, detail="Order not found.")

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
            impuesto_historico=Decimal("0.18"),
            monto_impuesto=item.monto_impuesto,
            subtotal_linea=item.subtotal_linea
        )
        db.add(detalle)

    db.commit()

    background_tasks.add_task(
        _sync_agregar_items_core,
        factura_local_uuid,
        payload.model_dump(mode="json")
    )

    return {"mensaje": "Items añadidos exitosamente.", "nuevo_total_general": float(pedido.total_general)}


async def _sync_agregar_items_core(factura_local_uuid: uuid.UUID, payload: dict):
    try:
        await core_client.patch(f"/api/v1/pedidos/{factura_local_uuid}/agregar-items", json=payload)
        logger.info(f"[BG-SYNC] Items for {factura_local_uuid} synchronized with CORE.")
    except Exception as e:
        logger.error(f"[BG-SYNC] Failed to synchronize items with CORE: {e}")


# ─── Solicitar cuenta ─────────────────────────────────────────────────────────

@router.post("/{factura_local_uuid}/solicitar-cuenta")
async def solicitar_cuenta(
        factura_local_uuid: uuid.UUID,
        payload: SolicitarCuentaRequest,
        db: Session = Depends(get_session)
):
    """Marks the order as POR_FACTURAR locally and notifies CORE."""
    pedido = db.exec(
        select(PedidoOffline).where(PedidoOffline.factura_local_uuid == factura_local_uuid)
    ).first()
    if not pedido:
        raise HTTPException(status_code=404, detail="Order not found.")

    pedido.propina_extra = payload.propina_extra
    pedido.total_general = pedido.subtotal + pedido.total_impuestos + pedido.propina_legal + pedido.propina_extra
    pedido.estado = "POR_FACTURAR"
    db.add(pedido)
    db.commit()

    # Fire-and-forget to CORE
    await core_client.post(
        f"/api/v1/pedidos/{factura_local_uuid}/solicitar-cuenta",
        json=payload.model_dump(mode="json")
    )

    return {"mensaje": f"Cuenta solicitada. Pago preferido: {payload.metodo_pago_preferido}"}


# ─── Dividir cuenta ───────────────────────────────────────────────────────────

@router.post("/{factura_local_uuid}/dividir-cuenta")
async def dividir_cuenta(
        factura_local_uuid: uuid.UUID,
        payload: dict,
        db: Session = Depends(get_session)
):
    """Proxies split-bill calculation to CORE (stateless, no local storage needed)."""
    pedido = db.get(PedidoOffline, factura_local_uuid)
    if not pedido:
        raise HTTPException(status_code=404, detail="Order not found.")

    core_response = await core_client.post(
        f"/api/v1/pedidos/{factura_local_uuid}/dividir-cuenta",
        json=payload
    )
    if core_response is None:
        raise HTTPException(status_code=503, detail="CORE unavailable to split the bill.")
    if "detail" in core_response:
        raise HTTPException(status_code=400, detail=core_response["detail"])
    return core_response


@router.get("/{factura_local_uuid}/division-cuenta")
async def obtener_division_cuenta(
        factura_local_uuid: uuid.UUID,
        db: Session = Depends(get_session)
):
    """Fetches split-bill result from CORE."""
    pedido = db.get(PedidoOffline, factura_local_uuid)
    if not pedido:
        raise HTTPException(status_code=404, detail="Order not found.")

    core_response = await core_client.get(f"/api/v1/pedidos/{factura_local_uuid}/division-cuenta")
    if core_response is None:
        raise HTTPException(status_code=503, detail="CORE unavailable.")
    if "detail" in core_response:
        raise HTTPException(status_code=404, detail=core_response["detail"])
    return core_response


# ─── Modificadores de item ────────────────────────────────────────────────────

@router.post("/{factura_local_uuid}/detalles/{detalle_pedido_uuid}/modificadores")
async def agregar_modificador_item(
        factura_local_uuid: uuid.UUID,
        detalle_pedido_uuid: uuid.UUID,
        payload: dict,
        db: Session = Depends(get_session)
):
    """Adds a special instruction to an item (e.g. 'no ice'). Proxied to CORE; returns CORE's response."""
    pedido = db.get(PedidoOffline, factura_local_uuid)
    if not pedido:
        raise HTTPException(status_code=404, detail="Pedido no encontrado localmente.")

    core_response = await core_client.post(
        f"/api/v1/pedidos/{factura_local_uuid}/detalles/{detalle_pedido_uuid}/modificadores",
        json=payload
    )
    if core_response is None:
        raise HTTPException(status_code=503, detail="CORE unavailable. The modifier could not be registered.")
    if "detail" in core_response:
        raise HTTPException(status_code=400, detail=core_response["detail"])
    return core_response
