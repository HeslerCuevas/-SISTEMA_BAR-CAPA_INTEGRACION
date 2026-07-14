from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.db.database import get_session
from app.api.deps import get_current_user_payload
from app.models.integration_models import Empleado
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
        raise HTTPException(status_code=503, detail=resultado["mensaje"])

    return resultado


@router.get("/locales", response_model=List[dict])
async def obtener_empleados_locales(
    db: Session = Depends(get_session)
):
    try:
        await sincronizar_personal_desde_core(db)
        print("Sincronización silenciosa exitosa antes de devolver empleados.")
    except Exception as e:
        print(f"Aviso: El CORE no está disponible para sincronización previa. Usando solo caché. Motivo: {e}")

    statement = select(Empleado).where(Empleado.activo == True)
    empleados_locales = db.exec(statement).all()

    if not empleados_locales:
        raise HTTPException(
            status_code=404,
            detail="La caché local está vacía y el CORE no respondió para poblarla."
        )

    resultado = []
    for emp in empleados_locales:
        resultado.append({
            "id": emp.id,
            "nombre_completo": emp.nombre_completo,
            "email": emp.email,
            "hash_clave": emp.password_hash
        })

    return resultado


@router.post("/sincronizar")
async def forzar_sincronizacion_personal(
    db: Session = Depends(get_session),
    usuario_actual: dict = Depends(get_current_user_payload)
):
    if usuario_actual.get("canal") != "CAJA":
        raise HTTPException(status_code=403, detail="Solo las cajas pueden sincronizar.")

    resultado = await sincronizar_personal_desde_core(db)

    if resultado["status"] == "error":
        raise HTTPException(status_code=503, detail=resultado["mensaje"])

    return resultado