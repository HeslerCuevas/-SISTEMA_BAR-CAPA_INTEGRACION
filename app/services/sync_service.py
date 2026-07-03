import logging
from sqlmodel import Session, select
from typing import Tuple

from app.models.integration_models import PedidoOffline, DetallePedidoOffline, MovimientoOffline
from app.clients.core_client import core_client

logger = logging.getLogger("SyncService")

async def procesar_pedidos_pendientes(db: Session) -> Tuple[int, int]:
    statement = select(PedidoOffline).where(PedidoOffline.estado_sincronizacion == "PENDIENTE")
    pedidos_pendientes = db.exec(statement).all()

    if not pedidos_pendientes:
        logger.info("No hay pedidos pendientes por sincronizar.")
        return 0, 0

    exitosos = 0
    fallidos = 0

    logger.info(f"Iniciando sincronización de {len(pedidos_pendientes)} pedidos...")

    for pedido in pedidos_pendientes:
        try:
            detalles_stmt = select(DetallePedidoOffline).where(DetallePedidoOffline.factura_local_uuid == pedido.factura_local_uuid)
            detalles = db.exec(detalles_stmt).all()

            # Build CORE-compatible payload — CORE only accepts these fields in PedidoCreate.
            # Totals/prices are intentionally excluded; CORE recalculates from its own catalog.
            canal_origen = pedido.canal_origen if pedido.canal_origen in ("CAJA", "MOVIL", "WEB") else "CAJA"
            payload_core = {
                "factura_local_uuid": str(pedido.factura_local_uuid),
                "empleado_id": pedido.empleado_id,
                "cliente_id": pedido.cliente_id,
                "canal_origen": canal_origen,
                "mesa": pedido.mesa,
                "propina_extra": float(pedido.propina_extra) if pedido.propina_extra else 0.0,
                "detalles": [
                    {
                        "producto_id": det.producto_id,
                        "cantidad": det.cantidad,
                        "detalle_local_uuid": str(det.detalle_local_uuid)
                    } for det in detalles
                ]
            }

            # CORE API is now prefixed with /api/v1
            respuesta = await core_client.post("/api/v1/pedidos/", json=payload_core)

            if respuesta:
                if pedido.estado == "FACTURADO":
                    logger.info(f"El pedido {pedido.factura_local_uuid} fue cobrado offline. Facturando en el CORE...")

                    resp_factura = await core_client.post(
                        f"/api/v1/pedidos/{pedido.factura_local_uuid}/facturar",
                        json={"empleado_id": pedido.empleado_id}
                    )

                    if not resp_factura:
                        logger.warning(f"Se subió el pedido {pedido.factura_local_uuid}, pero el CORE no lo facturó.")

                pedido.estado_sincronizacion = "COMPLETADO"
                pedido.ultimo_error = None
                exitosos += 1
                logger.info(f"Pedido {pedido.factura_local_uuid} sincronizado totalmente.")
            else:
                pedido.intentos_sincronizacion += 1
                pedido.ultimo_error = "CORE inalcanzable o devolvió error."
                fallidos += 1
                logger.warning(f"Fallo sync de {pedido.factura_local_uuid}. Intento {pedido.intentos_sincronizacion}")

            db.add(pedido)
            db.commit()

        except Exception as e:
            logger.error(f"Error crítico procesando pedido {pedido.factura_local_uuid}: {str(e)}")
            pedido.intentos_sincronizacion += 1
            pedido.ultimo_error = str(e)
            db.add(pedido)
            db.commit()
            fallidos += 1

    return exitosos, fallidos

async def procesar_movimientos_pendientes(session: Session):
    statement = select(MovimientoOffline).where(MovimientoOffline.estado_sincronizacion == "PENDIENTE")
    movimientos_pendientes = session.exec(statement).all()

    if not movimientos_pendientes:
        return 0, 0

    exitosos = 0
    fallidos = 0

    for mov in movimientos_pendientes:
        payload_core = {
            "movimiento_local_uuid": str(mov.id),
            "producto_id": mov.producto_id,
            "empleado_id": mov.empleado_id,
            "tipo_movimiento": mov.tipo_movimiento,
            "cantidad": mov.cantidad,
            "motivo": mov.motivo
        }

        # CORE API is now prefixed with /api/v1
        respuesta = await core_client.post("/api/v1/inventario/movimiento", json=payload_core)

        if respuesta:
            mov.estado_sincronizacion = "COMPLETADO"
            session.add(mov)
            exitosos += 1
        else:
            fallidos += 1

    session.commit()
    return exitosos, fallidos