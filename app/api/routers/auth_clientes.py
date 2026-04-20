from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status, Response
from sqlmodel import Session, select
import logging

from app.api.deps import get_current_user_payload
from app.models.integration_models import DispositivoCliente
from pydantic import BaseModel

from app.db.database import get_session
from app.clients.core_client import core_client
from app.models.integration_models import Cliente
from app.core.security import verify_password, get_password_hash, \
    create_access_token

from app.schemas.auth_schemas import (
    ClienteRegistroRequest,
    ClienteRegistroResponse,
    ClienteLoginRequest,
    ClienteLoginResponse
)

logger = logging.getLogger("RouterAuthClientes")
router = APIRouter(prefix="/clientes/auth", tags=["App Móvil - Autenticación"])


@router.post("/registro", response_model=ClienteRegistroResponse, status_code=201)
async def registrar_cliente_movil(
        request: ClienteRegistroRequest,
        response: Response,
        db: Session = Depends(get_session)
):
    logger.info(f"Intentando registrar nuevo cliente: {request.email}")

    core_response = await core_client.post("/clientes/auth/registro", json=request.model_dump())

    if core_response is None:
        raise HTTPException(
            status_code=503,
            detail="No hay conexión con el servidor central para crear cuentas nuevas. Intente más tarde."
        )
    if "detail" in core_response:
        raise HTTPException(status_code=400, detail=core_response["detail"])

    cliente_id = core_response.get("cliente_id")
    hashed_password = get_password_hash(request.password_plano)

    nuevo_cliente_local = Cliente(
        id=cliente_id,
        nombre_completo=request.nombre_completo,
        email=request.email,
        password_hash=hashed_password,
        puntos_lealtad=0
    )
    db.add(nuevo_cliente_local)
    db.commit()

    response.headers["X-Data-Source"] = "CORE_AND_CACHED"

    return ClienteRegistroResponse(
        mensaje="Cuenta creada y sincronizada en el bar",
        cliente_id=cliente_id,
        email=request.email
    )


@router.post("/login", response_model=ClienteLoginResponse)
async def login_cliente_movil(
        request: ClienteLoginRequest,
        response: Response,
        db: Session = Depends(get_session)
):
    logger.info(f"Intento de login cliente: {request.email}")

    core_response = await core_client.post("/clientes/auth/login", json=request.model_dump())

    if core_response is not None and "detail" not in core_response:
        response.headers["X-Data-Source"] = "CORE"
        return ClienteLoginResponse(**core_response)

    if core_response is not None and "detail" in core_response:
        raise HTTPException(status_code=401, detail=core_response["detail"])

    logger.warning("[FALLBACK] CORE inaccesible. Validando credenciales en SQL Server Local.")
    response.headers["X-Data-Source"] = "CACHE_LOCAL"

    statement = select(Cliente).where(Cliente.email == request.email)
    cliente_local = db.exec(statement).first()

    if not cliente_local or not verify_password(request.password_plano, cliente_local.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email o contraseña incorrectos (Validación Local)"
        )

    datos_token = {
        "sub": str(cliente_local.id),
        "canal": "MOVIL",
        "nombre": cliente_local.nombre_completo
    }

    token_real = create_access_token(data=datos_token)

    return ClienteLoginResponse(
        access_token=token_real,
        token_type="bearer",
        canal="MOVIL",
        cliente_id=cliente_local.id,
        nombre_completo=cliente_local.nombre_completo
    )


class TokenRequest(BaseModel):
    fcm_token: str
    plataforma: str


@router.post("/registrar-dispositivo")
async def registrar_dispositivo(
        request: TokenRequest,
        db: Session = Depends(get_session),
        usuario: dict = Depends(get_current_user_payload)
):
    cliente_id = int(usuario.get("sub"))

    statement = select(DispositivoCliente).where(DispositivoCliente.cliente_id == cliente_id)
    dispositivo = db.exec(statement).first()

    if dispositivo:
        dispositivo.fcm_token = request.fcm_token
        dispositivo.ultima_actualizacion = datetime.utcnow()
        dispositivo.plataforma = request.plataforma
    else:
        dispositivo = DispositivoCliente(
            cliente_id=cliente_id,
            fcm_token=request.fcm_token,
            plataforma=request.plataforma
        )

    db.add(dispositivo)
    db.commit()
    return {"status": "ok", "mensaje": "Token registrado exitosamente"}