from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.db.database import get_session
from app.api.deps import get_current_user_payload
from app.services.cache_service import sincronizar_personal_desde_core

router = APIRouter(prefix="/empleados", tags=["Gestion de Personal"])

@router.post("/sincronizar")
async def forzar_sincronizacion_personal(
    db: Session = Depends(get_session),
    usuario_actual: dict = Depends(get_current_user_payload)
):
    if usuario_actual.get("canal") != "CAJA":
        raise HTTPException(
            status_code=403,
            detail="Operación denegada. Solo terminales de caja pueden sincronizar catálogos."
        )

    resultado = await sincronizar_personal_desde_core(db)

    if resultado["status"] == "error":
        # CORE APAGADO, devolvemos un 503 Service Unavailable
        raise HTTPException(status_code=503, detail=resultado["mensaje"])

    return resultado