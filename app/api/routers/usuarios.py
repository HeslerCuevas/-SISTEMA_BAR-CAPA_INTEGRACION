from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from typing import List, Dict, Any
import logging

from app.db.database import get_session
from app.core.config import settings
from app.api.deps import get_current_user_payload
from app.models.integration_models import Empleado

logger = logging.getLogger("RouterUsuarios")
router = APIRouter(prefix="/usuarios", tags=["Gestión de Personal Local"])


@router.get("/me")
def obtener_mi_perfil(
        db: Session = Depends(get_session),
        usuario_actual: dict = Depends(get_current_user_payload)
) -> Dict[str, Any]:
    empleado_id = usuario_actual.get("sub")

    empleado = db.exec(select(Empleado).where(Empleado.id == empleado_id)).first()

    if not empleado:
        logger.warning(f"Intento de acceso con token válido pero usuario inexistente localmente: {empleado_id}")
        raise HTTPException(status_code=404, detail="Usuario no encontrado en la caché local.")

    return {
        "id": empleado.id,
        "nombre_completo": empleado.nombre_completo,
        "documento_identidad": empleado.documento_identidad,
        "gmail": empleado.gmail,
        "sucursal_id": empleado.sucursal_id,
        "rol_id": empleado.rol_id,
        "activo": empleado.activo
    }


@router.get("/sucursal")
def listar_personal_sucursal(
        db: Session = Depends(get_session),
        usuario_actual: dict = Depends(get_current_user_payload)  # Protegemos el endpoint
) -> List[Dict[str, Any]]:

    statement = select(Empleado).where(
        Empleado.sucursal_id == settings.SUCURSAL_ID,
        Empleado.activo == True
    )

    empleados_locales = db.exec(statement).all()

    resultados = []
    for emp in empleados_locales:
        resultados.append({
            "id": emp.id,
            "nombre": emp.nombre_completo,
            "rol_id": emp.rol_id
        })

    return resultados