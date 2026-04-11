from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlmodel import Session, select
from app.db.database import get_session
from app.schemas.auth_schemas import TokenResponse
from app.models.integration_models import Empleado
from app.core.security import verify_password, create_access_token

router = APIRouter(prefix="/auth", tags=["Autenticación"])


@router.post("/login", response_model=TokenResponse)
def login(
        form_data: OAuth2PasswordRequestForm = Depends(),
        db: Session = Depends(get_session)
):
    statement = select(Empleado).where(Empleado.documento_identidad == form_data.username)
    empleado = db.exec(statement).first()

    if not empleado:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no encontrado en la cache local."
        )

    if not verify_password(form_data.password, empleado.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Contraseña incorrecta."
        )

    if not empleado.activo:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="El usuario está inactivo."
        )

    access_token = create_access_token(subject=empleado.id, canal="CAJA")

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        canal="CAJA",
        usuario_id=empleado.id
    )