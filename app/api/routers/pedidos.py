from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select
from app.db.database import get_session
from app.models.schemas import LoginRequest, TokenResponse
from app.models.integration_models import Empleado
from app.core.security import verify_password, create_access_token

router = APIRouter(prefix="/pedidos", tags=["Pedidos"])

@router.post("/login", response_model=TokenResponse)
def login(request: LoginRequest, db: Session = Depends(get_session)):
    statement = select(Empleado).where(Empleado.documento_identidad == request.identificador)
    empleado = db.exec(statement).first()

    if not empleado:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no encontrado en la caché local."
        )

    if not verify_password(request.password, empleado.password_hash):
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