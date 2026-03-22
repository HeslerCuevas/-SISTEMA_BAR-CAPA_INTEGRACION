from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException
from sqlmodel import Session
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
    """
    Esta función corre en SEGUNDO PLANO. No hace esperar al mesero.
    Intenta enviar el pedido al CORE. Si falla, se queda como 'PENDIENTE' localmente.
    """
    logger.info(f"[BACKGROUND] Intentando subir pedido {pedido_uuid} al CORE...")

    # Preparamos el payload añadiendo el UUID local para que el CORE no lo duplique si hay reintentos
    payload_core = data_pedido.copy()
    payload_core["integracion_uuid"] = str(pedido_uuid)

    respuesta = await core_client.post("/pedidos/", data=payload_core)

    # Aquí en el futuro (en el sync_service) abriremos una nueva sesión de BD
    # para cambiar el estado de 'PENDIENTE' a 'COMPLETADO' si la respuesta es exitosa.
    if respuesta:
        logger.info(f"[BACKGROUND] Pedido {pedido_uuid} sincronizado con éxito.")
    else:
        logger.warning(f"⚠[BACKGROUND] CORE inalcanzable. Pedido {pedido_uuid} encolado para reintento.")


@router.post("/", response_model=PedidoResponse, status_code=201)
async def crear_pedido(
        request: PedidoRequest,
        background_tasks: BackgroundTasks,  # <--- LA MAGIA DE FASTAPI
        db: Session = Depends(get_session),
        usuario_actual: dict = Depends(get_current_user_payload)
):
    """
    Recibe un pedido, lo guarda localmente de forma segura y lanza
    un proceso en segundo plano para sincronizarlo con el CORE.
    """
    # 1. GENERAR IDENTIFICADOR ÚNICO (Para evitar duplicados en el CORE)
    nuevo_uuid = uuid.uuid4()

    # 2. GUARDAR EN LA BASE DE DATOS LOCAL (Esquema Sync)
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
            estado_sincronizacion="PENDIENTE"  # Vital: Nace pendiente de subir
        )
        db.add(nuevo_pedido)

        for det in request.detalles:
            nuevo_detalle = DetallePedidoOffline(
                factura_local_uuid=nuevo_uuid,
                producto_id=det.producto_id,
                cantidad=det.cantidad,
                precio_unitario_historico=det.precio_unitario,
                impuesto_historico=0,  # Simplificado para el ejemplo
                monto_impuesto=det.monto_impuesto,
                subtotal_linea=det.subtotal_linea
            )
            db.add(nuevo_detalle)

        db.commit()
        logger.info(f"💾 Pedido {nuevo_uuid} guardado en Caché Local.")

    except Exception as e:
        db.rollback()
        logger.critical(f"Error guardando pedido localmente: {e}")
        raise HTTPException(status_code=500, detail="Error crítico guardando la orden localmente.")

    # 3. LANZAR TAREA EN SEGUNDO PLANO
    # Le pasamos la función y los argumentos. FastAPI lo ejecutará DESPUÉS de responder.
    background_tasks.add_task(intentar_sincronizar_pedido, nuevo_uuid, request.model_dump())

    # 4. RESPONDER INMEDIATAMENTE AL CLIENTE
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
    """
    Endpoint manual para que el Administrador fuerce la subida de todos
    los pedidos offline que se quedaron atascados durante una caída de red.
    Ideal para ejecutar durante el "Cierre de Caja".
    """
    # 1. Validación de seguridad extra: Solo personal de CAJA puede hacer esto
    if usuario_actual.get("canal") != "CAJA":
        raise HTTPException(
            status_code=403,
            detail="Operación no permitida. Solo disponible en terminales de Caja."
        )

    # 2. Llamar al servicio pesado
    exitosos, fallidos = await procesar_pedidos_pendientes(db)

    # 3. Retornar el resumen al frontend (Caja WPF)
    return {
        "mensaje": "Proceso de sincronización finalizado.",
        "resultados": {
            "exitosos": exitosos,
            "fallidos": fallidos,
            "total_procesados": exitosos + fallidos
        }
    }


@router.post("/{id}/facturar")
async def facturar_pedido(
    id: str, # UUID del pedido local
    db: Session = Depends(get_session)
):
    """
    Cambia el estado del pedido a 'FACTURADO'.
    Si el CORE está disponible, cierra la venta allá también.
    """
    # 1. Buscar pedido localmente
    # 2. Cambiar estado en SQL Server
    # 3. Intentar notificar al CORE
    respuesta = await core_client.post(f"/pedidos/{id}/facturar", data={})
    return {"mensaje": f"Pedido {id} facturado correctamente.", "sync": "EXITOSA" if respuesta else "PENDIENTE"}

@router.post("/{id}/cancelar")
async def cancelar_pedido(
    id: str,
    db: Session = Depends(get_session)
):
    """Anula un pedido por error de digitación o devolución."""
    respuesta = await core_client.post(f"/pedidos/{id}/cancelar", data={})
    return {"mensaje": f"Pedido {id} cancelado.", "core_notificado": bool(respuesta)}