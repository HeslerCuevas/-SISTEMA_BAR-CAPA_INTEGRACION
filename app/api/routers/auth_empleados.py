from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlmodel import Session, select
from sqlalchemy import or_
import logging
import httpx

from app.db.database import get_session
from app.schemas.auth_schemas import TokenResponse
from app.models.integration_models import Empleado
from app.core.security import verify_password, create_access_token
from app.core.config import settings

logger = logging.getLogger("AuthRouter")
router = APIRouter(prefix="/auth", tags=["Autenticación"])

# Built from settings so CORE_URL in .env is the single source of truth
CORE_AUTH_URL = f"{settings.CORE_URL}/api/v1/auth/login"


@router.post("/login", response_model=TokenResponse)
async def login(
        form_data: OAuth2PasswordRequestForm = Depends(),
        db: Session = Depends(get_session)
):
    print(f"Intentando login para el usuario: '{form_data.username}'")

    core_online = False
    core_data = None

    try:
        async with httpx.AsyncClient() as client:

            headers = {
                "x-gateway-token": settings.SECRET_KEY
            }

            response = await client.post(
                CORE_AUTH_URL,
                data={"username": form_data.username, "password": form_data.password},
                headers=headers,
                timeout=3.0
            )

            if response.status_code == 200:
                core_online = True
                core_data = response.json()
                print("Conexión con CORE exitosa. Credenciales validadas remotamente.")
            elif response.status_code in [401, 403]:
                print(f"CORE rechazó el acceso: HTTP {response.status_code}")
                # Si el CORE devuelve error, extraemos el detalle
                err_detail = response.json().get("detail", "Acceso denegado por el servidor central.")
                raise HTTPException(
                    status_code=response.status_code,
                    detail=err_detail
                )
    except httpx.RequestError as e:
        print(f"⚠️ CORE inalcanzable, procediendo con validación Offline (Local Cache): {e}")
    except HTTPException:
        raise

    statement = select(Empleado).where(
        or_(
            Empleado.email == form_data.username,
            Empleado.documento_identidad == form_data.username
        )
    )
    empleado_local = db.exec(statement).first()

    if core_online and core_data:
        if not empleado_local:
            empleado_local = Empleado(
                id=core_data["empleado_id"],
                email=form_data.username,
                nombre_completo=core_data["nombre"],
                activo=core_data["activo"],
                # These fields are required by the model; fallback to empty strings until next full sync
                documento_identidad="",
                password_hash="",
                rol_id=0,
                sucursal_id=core_data.get("sucursal_id", 1)
            )
            db.add(empleado_local)
        else:
            empleado_local.nombre_completo = core_data["nombre"]
            empleado_local.activo = core_data["activo"]
            empleado_local.email = form_data.username

        db.commit()
        db.refresh(empleado_local)

    if not empleado_local:
        print(f"No se encontró registro local para: '{form_data.username}'")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User or Password invalid."
        )

    if not core_online:
        if not verify_password(form_data.password, empleado_local.password_hash):
            print(f"Password incorrecto para: {form_data.username}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User or Password invalid."
            )

    if not empleado_local.activo:
        print(f"Intento de login de usuario inactivo: {form_data.username}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="El usuario está inactivo en el sistema."
        )

    access_token = create_access_token(
        subject=str(empleado_local.id),
        canal="CAJA"
    )

    print(f"Login exitoso. Generando token para ID: {empleado_local.id}")

    rol_final = "Cajero"
    if core_online:
        rol_final = core_data["rol"]
    else:
        if hasattr(empleado_local, 'rol') and empleado_local.rol:
            rol_final = getattr(empleado_local.rol, 'nombre', str(empleado_local.rol))

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        canal="CAJA",
        usuario_id=empleado_local.id,
        nombre=empleado_local.nombre_completo,
        rol=rol_final,
        sucursal_id=core_data["sucursal_id"] if core_online else getattr(empleado_local, 'sucursal_id', 1)
    )