from fastapi import APIRouter, Depends
from sqlmodel import Session, select, func
from app.db.database import get_session
from app.models.integration_models import PedidoOffline
from app.clients.core_client import core_client

router = APIRouter(prefix="/reportes", tags=["Reportes y Dashboards"])


@router.get("/ventas-hoy")
async def get_ventas_hoy(db: Session = Depends(get_session)):
    # 1. Intentar obtener el reporte consolidado del CORE
    reporte_core = await core_client.get("/reportes/ventas-hoy")

    if reporte_core:
        return reporte_core

    # 2. Si el CORE falla, calcular basado en lo que ha pasado por este Gateway hoy
    statement = select(func.sum(PedidoOffline.total_general))
    total_local = db.exec(statement).one() or 0

    return {
        "ventas_totales": total_local,
        "origen": "SOLO LOCAL (MODO CONTINGENCIA)",
        "mensaje": "Este reporte solo incluye ventas realizadas en esta sucursal."
    }