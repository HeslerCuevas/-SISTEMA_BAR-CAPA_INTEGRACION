from fastapi import APIRouter, Depends, HTTPException, status, Response, BackgroundTasks
from sqlmodel import Session, select
import logging

from app.db.database import get_session
from app.clients.core_client import core_client
from app.models.integration_models import Cliente
from app.core.security import verify_password, get_password_hash, \
    create_access_token  # <-- Importamos creador de tokens

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
    """
    Intenta registrar al cliente en el CORE global.
    Si tiene éxito, lo guarda inmediatamente en la Caché Local para que pueda hacer login offline.
    """
    logger.info(f"Intentando registrar nuevo cliente: {request.email}")

    # 1. Enviar petición al CORE usando tu cliente HTTP
    core_response = await core_client.post("/clientes/auth/registro", data=request.model_dump())

    if core_response is None:
        # Fallback: El CORE está caído.
        raise HTTPException(
            status_code=503,
            detail="No hay conexión con el servidor central para crear cuentas nuevas. Intente más tarde."
        )

    # Si el CORE devuelve error (ej. email duplicado), propagarlo
    if "detail" in core_response:
        raise HTTPException(status_code=400, detail=core_response["detail"])

    # 2. Éxito en el CORE. Guardar en Caché Local del Gateway inmediatamente
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
    """
    [OFFLINE-FIRST] Intenta validar con el CORE. Si no hay internet, valida contra la Base de Datos Local.
    """
    logger.info(f"Intento de login cliente: {request.email}")

    # 1. Intentar validar con el CORE
    core_response = await core_client.post("/clientes/auth/login", data=request.model_dump())

    if core_response is not None and "detail" not in core_response:
        # ¡Internet funciona y credenciales correctas!
        response.headers["X-Data-Source"] = "CORE"
        return ClienteLoginResponse(**core_response)

    # Si el CORE respondió explícitamente con un error 401 (Credenciales malas)
    if core_response is not None and "detail" in core_response:
        raise HTTPException(status_code=401, detail=core_response["detail"])

    # 2. FALLBACK (No hay internet / CORE Caído) -> Buscar en Caché Local
    logger.warning("[FALLBACK] CORE inaccesible. Validando credenciales en SQL Server Local.")
    response.headers["X-Data-Source"] = "CACHE_LOCAL"

    statement = select(Cliente).where(Cliente.email == request.email)
    cliente_local = db.exec(statement).first()

    if not cliente_local or not verify_password(request.password_plano, cliente_local.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email o contraseña incorrectos (Validación Local)"
        )

    # 3. GENERAR EL TOKEN JWT REAL PARA MODO OFFLINE
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