from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm  # <--- NUEVA IMPORTACIÓN
from sqlmodel import Session, select
from app.db.database import get_session
from app.schemas.auth_schemas import TokenResponse
from app.models.integration_models import Empleado
from app.core.security import verify_password, create_access_token

router = APIRouter(prefix="/auth", tags=["Autenticación"])


@router.post("/login", response_model=TokenResponse)
def login(
        # Cambiamos LoginRequest por el formulario estándar de OAuth2
        form_data: OAuth2PasswordRequestForm = Depends(),
        db: Session = Depends(get_session)
):
    """
    Endpoint de Login compatible con Swagger y estándares OAuth2.
    - form_data.username: Se mapea a nuestro 'identificador' (Documento)
    - form_data.password: La clave del usuario
    """

    # 1. Buscar al empleado por su documento (usando form_data.username)
    statement = select(Empleado).where(Empleado.documento_identidad == form_data.username)
    empleado = db.exec(statement).first()

    # 2. Validar si existe
    if not empleado:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no encontrado en la caché local."
        )

    # 3. Validar la contraseña
    if not verify_password(form_data.password, empleado.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Contraseña incorrecta."
        )

    # 4. Validar si está activo
    if not empleado.activo:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="El usuario está inactivo."
        )

    # 5. Generar el Token JWT
    access_token = create_access_token(subject=empleado.id, canal="CAJA")

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        canal="CAJA",
        usuario_id=empleado.id
    )