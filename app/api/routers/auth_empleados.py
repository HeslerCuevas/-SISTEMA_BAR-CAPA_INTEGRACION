from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlmodel import Session, select
from sqlalchemy import or_
import logging

# Importaciones de tu proyecto
from app.db.database import get_session
from app.schemas.auth_schemas import TokenResponse
from app.models.integration_models import Empleado
from app.core.security import verify_password, create_access_token

# Configuración de logger para ver errores en consola
logger = logging.getLogger("AuthRouter")
router = APIRouter(prefix="/auth", tags=["Autenticación"])


@router.post("/login", response_model=TokenResponse)
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_session)
):
    """
    Endpoint de Login para la Capa de Integración.
    Permite el acceso usando el Gmail o el Documento de Identidad (Cédula).
    """
    print(f"🔍 Intentando login para el usuario: '{form_data.username}'")

    # 1. Búsqueda Dual: Intentamos encontrar al empleado por correo O por cédula
    statement = select(Empleado).where(
        or_(
            Empleado.gmail == form_data.username,
            Empleado.documento_identidad == form_data.username
        )
    )

    empleado = db.exec(statement).first()

    # 2. Verificación de existencia
    if not empleado:
        print(f"❌ No se encontró registro para: '{form_data.username}'")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no encontrado en la cache local."
        )

    print(f"✅ Usuario encontrado: {empleado.nombre_completo}")

# 3. VERIFICACIÓN DE CONTRASEÑA REAL (Producción)
    try:
        # Intentamos obtener el hash de la base de datos (manejando posibles nombres de columna)
        password_db_hash = getattr(empleado, "PasswordHash", getattr(empleado, "password_hash", None))
        
        if not password_db_hash:
            print(f"❌ El usuario {form_data.username} no tiene un hash de contraseña definido.")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error de configuración de seguridad en el servidor."
            )

        # Verificamos si la contraseña plana coincide con el hash Bcrypt
        if not verify_password(form_data.password, password_db_hash):
            print(f"🔑 Intento fallido: Contraseña incorrecta para {form_data.username}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, 
                detail="Credenciales inválidas."
            )
            
        print(f"🔒 Verificación criptográfica exitosa para: {empleado.nombre_completo}")

    except HTTPException:
        raise
    except Exception as e:
        print(f"🔥 Error inesperado en seguridad: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Fallo interno en la validación de seguridad."
        )

    # 4. Verificación de estado activo
    if not empleado.activo:
        print(f"🚫 Intento de login de usuario inactivo: {form_data.username}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="El usuario está inactivo en el sistema."
        )

    # 5. Generación del Token
    access_token = create_access_token(
        subject=str(empleado.id),
        canal="CAJA"
    )

    print(f"🚀 Login exitoso. Generando token para ID: {empleado.id}")

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        canal="CAJA",
        usuario_id=empleado.id
    )
