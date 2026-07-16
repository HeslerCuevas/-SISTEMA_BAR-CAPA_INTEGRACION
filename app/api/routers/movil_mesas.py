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
router = APIRouter(prefix="/clientes/mesas", tags=["Gestión de Mesas"])
legacy_router = APIRouter(prefix="/mesas", tags=["Gestión de Mesas"])


@router.post("/vincular", response_model=MesaVincularResponse)
@legacy_router.post("/vincular", response_model=MesaVincularResponse, include_in_schema=False)
async def vincular_mesa_movil(
        request: MesaVincularRequest,
        response: Response,
        db: Session = Depends(get_session)
):
    logger.info(f"Customer scanned the QR code for Table {request.numero_mesa}")

    core_data = await core_client.post("/api/v1/mesas/vincular", json=request.model_dump())

    if core_data is not None and "detail" not in core_data:
        response.headers["X-Data-Source"] = "CORE"
        return MesaVincularResponse(**core_data)

    if core_data is not None and "detail" in core_data:
        raise HTTPException(
            status_code=core_data.get("_status_code", 400),
            detail=core_data["detail"]
        )

    response.headers["X-Data-Source"] = "CACHE_LOCAL"
    logger.warning("[FALLBACK] CORE unreachable. Checking table status locally.")


    statement = select(PedidoOffline).where(
        PedidoOffline.mesa == request.numero_mesa
    ).order_by(PedidoOffline.fecha_creacion_local.desc())

    ultimo_pedido = db.exec(statement).first()

    if ultimo_pedido and ultimo_pedido.estado_sincronizacion in ["PENDIENTE", "ERROR"]:
        return MesaVincularResponse(
            mensaje="Table occupied (local validation).",
            estado_mesa="ABIERTA",
            numero_mesa=request.numero_mesa,
            factura_local_uuid_activa=ultimo_pedido.factura_local_uuid
        )

    return MesaVincularResponse(
        mensaje="Table available (local validation).",
        estado_mesa="LIBRE",
        numero_mesa=request.numero_mesa,
        factura_local_uuid_activa=None
    )


@router.post("/{numero_mesa}/llamar-mesero", response_model=LlamarMeseroResponse)
@legacy_router.post("/{numero_mesa}/llamar-mesero", response_model=LlamarMeseroResponse, include_in_schema=False)
async def llamar_mesero_movil(
        numero_mesa: int,
        request: LlamarMeseroRequest,
        response: Response
):
    core_data = await core_client.post(f"/api/v1/mesas/{numero_mesa}/llamar-mesero", json=request.model_dump())

    if core_data is not None and "detail" not in core_data:
        response.headers["X-Data-Source"] = "CORE"
        return LlamarMeseroResponse(**core_data)

    if core_data is not None and "detail" in core_data:
        raise HTTPException(
            status_code=core_data.get("_status_code", 400),
            detail=core_data["detail"]
        )

    response.headers["X-Data-Source"] = "LOCAL_NETWORK"
    logger.warning(f"LOCAL ALERT! Table {numero_mesa} requests {request.motivo_llamada}")


    return LlamarMeseroResponse(
        mensaje=f"Alert sent to the bar's local cash register."
    )
