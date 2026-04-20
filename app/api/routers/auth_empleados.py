from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlmodel import Session, select
from sqlalchemy import or_
import logging

from app.db.database import get_session
from app.schemas.auth_schemas import TokenResponse
from app.models.integration_models import Empleado
from app.core.security import verify_password, create_access_token

logger = logging.getLogger("AuthRouter")
router = APIRouter(prefix="/auth", tags=["Autenticación"])


@router.post("/login", response_model=TokenResponse)
def login(
        form_data: OAuth2PasswordRequestForm = Depends(),
        db: Session = Depends(get_session)
):
    print(f"Intentando login para el usuario: '{form_data.username}'")

    statement = select(Empleado).where(
        or_(
            Empleado.gmail == form_data.username,
            Empleado.documento_identidad == form_data.username
        )
    )

    empleado = db.exec(statement).first()

    if not empleado:
        print(f"No se encontró registro para: '{form_data.username}'")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no encontrado en la cache local."
        )

    print(f"Usuario encontrado: {empleado.nombre_completo}")

    if not verify_password(form_data.password, empleado.password_hash):
        print(f"Password incorrecto para: {form_data.username}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Contraseña incorrecta."
        )

    if not empleado.activo:
        print(f"Intento de login de usuario inactivo: {form_data.username}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="El usuario está inactivo en el sistema."
        )

    access_token = create_access_token(
        subject=str(empleado.id),
        canal="CAJA"
    )

    print(f"Login exitoso. Generando token para ID: {empleado.id}")

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        canal="CAJA",
        usuario_id=empleado.id
    )