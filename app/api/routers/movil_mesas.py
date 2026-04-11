from fastapi import APIRouter, Depends, HTTPException, Response
from sqlmodel import Session, select
import logging

from app.db.database import get_session
from app.clients.core_client import core_client
from app.models.integration_models import PedidoOffline
from app.schemas.mesas_schema import (
    MesaVincularRequest, MesaVincularResponse,
    LlamarMeseroRequest, LlamarMeseroResponse
)

logger = logging.getLogger("RouterMesasGateway")
router = APIRouter(prefix="/clientes/mesas", tags=["App Móvil - Mesas y QR"])


@router.post("/vincular", response_model=MesaVincularResponse)
async def vincular_mesa_movil(
        request: MesaVincularRequest,
        response: Response,
        db: Session = Depends(get_session)
):
    """
    [OFFLINE-FIRST] Verifica el estado de la mesa escaneada.
    """
    logger.info(f"Cliente escaneó QR de la Mesa {request.numero_mesa}")

    # 1. INTENTO DE RED: Preguntarle al CORE (Si hay internet)
    core_data = await core_client.post("/mesas/vincular", data=request.model_dump())

    if core_data is not None and "detail" not in core_data:
        response.headers["X-Data-Source"] = "CORE"
        return MesaVincularResponse(**core_data)

    # 2. FALLBACK OFFLINE: Buscar en la base de datos local del Gateway
    response.headers["X-Data-Source"] = "CACHE_LOCAL"
    logger.warning("[FALLBACK] CORE inaccesible. Verificando estado de mesa localmente.")

    # Buscamos en PedidoOffline ordenando por fecha para obtener la más reciente
    statement = select(PedidoOffline).where(
        PedidoOffline.mesa == request.numero_mesa
    ).order_by(PedidoOffline.fecha_creacion_local.desc())

    ultimo_pedido = db.exec(statement).first()

    # Si el último pedido de esa mesa NO está "COMPLETADO" (Facturado), asumimos que sigue abierta
    if ultimo_pedido and ultimo_pedido.estado_sincronizacion in ["PENDIENTE", "ERROR"]:
        return MesaVincularResponse(
            mensaje="Mesa ocupada (Validación Local).",
            estado_mesa="ABIERTA",
            numero_mesa=request.numero_mesa,
            factura_local_uuid_activa=ultimo_pedido.factura_local_uuid
        )

    # Si no hay pedidos recientes o ya están cerrados
    return MesaVincularResponse(
        mensaje="Mesa libre (Validación Local).",
        estado_mesa="LIBRE",
        numero_mesa=request.numero_mesa,
        factura_local_uuid_activa=None
    )


@router.post("/{numero_mesa}/llamar-mesero", response_model=LlamarMeseroResponse)
async def llamar_mesero_movil(
        numero_mesa: int,
        request: LlamarMeseroRequest,
        response: Response
):
    """
    [OFFLINE-FIRST] Notifica a los meseros. Si no hay internet, solo alerta a la caja local.
    """
    # 1. Intentar enviar la alerta al CORE
    core_data = await core_client.post(f"/mesas/{numero_mesa}/llamar-mesero", data=request.model_dump())

    if core_data is not None and "detail" not in core_data:
        response.headers["X-Data-Source"] = "CORE"
        return LlamarMeseroResponse(**core_data)

    # 2. FALLBACK: Alertar solo a la Caja Local
    response.headers["X-Data-Source"] = "LOCAL_NETWORK"
    logger.warning(f"¡ALERTA LOCAL! Mesa {numero_mesa} solicita {request.motivo_llamada}")

    # Aquí en un futuro podrías insertar un registro en una tabla local [Logs_Caja]
    # para que la pantalla del POS haga un sonido o muestre un pop-up rojo.

    return LlamarMeseroResponse(
        mensaje=f"Alerta enviada a la caja local del bar."
    )