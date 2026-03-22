import logging
from sqlmodel import Session, select
from typing import Tuple

from app.models.integration_models import PedidoOffline, DetallePedidoOffline
from app.clients.core_client import core_client

logger = logging.getLogger("SyncService")

async def procesar_pedidos_pendientes(db: Session) -> Tuple[int, int]:
    """
    Busca todos los pedidos en estado 'PENDIENTE' en la base de datos local
    e intenta enviarlos al CORE en lote (batch).
    Retorna una tupla: (pedidos_exitosos, pedidos_fallidos)
    """
    # 1. Buscar pedidos pendientes
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
            # 2. Reconstruir el JSON del pedido con sus detalles
            detalles_stmt = select(DetallePedidoOffline).where(DetallePedidoOffline.factura_local_uuid == pedido.factura_local_uuid)
            detalles = db.exec(detalles_stmt).all()

            payload_core = {
                "factura_local_uuid": str(pedido.factura_local_uuid),
                "empleado_id": pedido.empleado_id,
                "cliente_id": pedido.cliente_id,
                "canal_origen": pedido.canal_origen,
                "mesa": pedido.mesa,
                "subtotal": float(pedido.subtotal),
                "total_impuestos": float(pedido.total_impuestos),
                "propina_legal": float(pedido.propina_legal),
                "total_general": float(pedido.total_general),
                "fecha_creacion_local": pedido.fecha_creacion_local.isoformat(),
                "detalles": [
                    {
                        "producto_id": det.producto_id,
                        "cantidad": det.cantidad,
                        "precio_unitario": float(det.precio_unitario_historico),
                        "monto_impuesto": float(det.monto_impuesto),
                        "subtotal_linea": float(det.subtotal_linea)
                    } for det in detalles
                ]
            }

            # 3. Enviar al CORE
            respuesta = await core_client.post("/pedidos/", data=payload_core)

            # 4. Actualizar estado según la respuesta
            if respuesta:
                pedido.estado_sincronizacion = "COMPLETADO"
                pedido.ultimo_error = None
                exitosos += 1
                logger.info(f"✅ Pedido {pedido.factura_local_uuid} sincronizado.")
            else:
                pedido.intentos_sincronizacion += 1
                pedido.ultimo_error = "CORE inalcanzable o devolvió error."
                fallidos += 1
                logger.warning(f"⚠️ Falló sync de {pedido.factura_local_uuid}. Intento {pedido.intentos_sincronizacion}")

            # Guardamos el cambio de estado de este pedido
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