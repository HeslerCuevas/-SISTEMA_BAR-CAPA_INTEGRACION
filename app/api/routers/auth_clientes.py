from datetime import datetime
from app.core.timezone import get_local_now

from fastapi import APIRouter, Depends, HTTPException, status, Response, Request
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
    logger.info(f"Attempting to register new customer: {request.email}")

    core_response = await core_client.post("/api/v1/clientes/auth/registro", json=request.model_dump())

    if core_response is None:
        raise HTTPException(
            status_code=503,
            detail="There is no connection to the central server to create new accounts. Please try again later."
        )
    if "detail" in core_response:
        # Forward the exact detail and its natural HTTP status code so the mobile app
        # can distinguish errors (e.g. 400 email-already-registered vs validation errors).
        # The CORE uses 400 for all registration business-rule violations.
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
        mensaje="Account created and synchronized with the bar",
        cliente_id=cliente_id,
        email=request.email,
        email_verificado=core_response.get("email_verificado", False),
    )


@router.post("/login", response_model=ClienteLoginResponse)
async def login_cliente_movil(
        request: ClienteLoginRequest,
        response: Response,
        db: Session = Depends(get_session)
):
    logger.info(f"Customer login attempt: {request.email}")

    core_response = await core_client.post("/api/v1/clientes/auth/login", json=request.model_dump())

    if core_response is not None and "detail" not in core_response:
        response.headers["X-Data-Source"] = "CORE"
        return ClienteLoginResponse(**core_response)

    if core_response is not None and "detail" in core_response:
        detail = core_response["detail"]
        # CORE returns 403 for inactive accounts with a distinguishable prefix.
        # Forward it so Flutter can show the reactivation prompt.
        if "CUENTA_INACTIVA" in str(detail):
            raise HTTPException(status_code=403, detail=detail)
        raise HTTPException(status_code=401, detail=detail)

    logger.warning("[FALLBACK] CORE unreachable. Validating credentials in local SQL Server.")
    response.headers["X-Data-Source"] = "CACHE_LOCAL"

    statement = select(Cliente).where(Cliente.email == request.email)
    cliente_local = db.exec(statement).first()

    if not cliente_local or not verify_password(request.password_plano, cliente_local.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password (local validation)"
        )

    # Local fallback inactive check
    if not cliente_local.activo:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="INACTIVE_ACCOUNT: This account has been deactivated. Request reactivation from the app."
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
        dispositivo.ultima_actualizacion = get_local_now()
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


# ─── Cambio de contraseña ─────────────────────────────────────────────────────

@router.post("/cambiar-password")
async def cambiar_password_cliente(
        request: Request,
        db: Session = Depends(get_session),
        usuario: dict = Depends(get_current_user_payload)
):
    """Proxy al CORE. Requiere token del cliente en el header Authorization."""
    body = await request.json()
    core_response = await core_client.post(
        "/api/v1/clientes/auth/cambiar-password",
        json=body,
        headers={"Authorization": request.headers.get("Authorization", "")}
    )
    if core_response is None:
        raise HTTPException(status_code=503, detail="CORE unavailable. Please try again later.")
    if "detail" in core_response:
        raise HTTPException(status_code=400, detail=core_response["detail"])
    return core_response


# ─── Solicitar reset de contraseña ───────────────────────────────────────────

@router.post("/solicitar-reset")
async def solicitar_reset_cliente(
        request: Request
):
    """Proxy al CORE. Genera y envía email de recuperación. CORE es el único que puede enviar emails."""
    body = await request.json()
    core_response = await core_client.post("/api/v1/clientes/auth/solicitar-reset", json=body)
    if core_response is None:
        raise HTTPException(status_code=503, detail="CORE unavailable. Please try again later.")
    return core_response


# ─── Confirmar reset de contraseña ───────────────────────────────────────────

@router.post("/confirmar-reset")
async def confirmar_reset_cliente(
        request: Request
):
    """Proxy al CORE. Valida el token de reset y cambia la contraseña."""
    body = await request.json()
    core_response = await core_client.post("/api/v1/clientes/auth/confirmar-reset", json=body)
    if core_response is None:
        raise HTTPException(status_code=503, detail="CORE unavailable. Please try again later.")
    if "detail" in core_response:
        raise HTTPException(status_code=400, detail=core_response["detail"])
    return core_response


@router.post("/confirmar-reset-otp")
async def confirmar_reset_cliente_otp(
        request: Request
):
    body = await request.json()
    core_response = await core_client.post("/api/v1/clientes/auth/confirmar-reset-otp", json=body)
    if core_response is None:
        raise HTTPException(status_code=503, detail="CORE unavailable. Please try again later.")
    if "detail" in core_response:
        raise HTTPException(status_code=400, detail=core_response["detail"])
    return core_response


@router.post("/solicitar-verificacion-email")
async def solicitar_verificacion_email_cliente(
        request: Request,
        usuario: dict = Depends(get_current_user_payload)
):
    core_response = await core_client.post(
        "/api/v1/clientes/auth/solicitar-verificacion-email",
        headers={"Authorization": request.headers.get("Authorization", "")}
    )
    if core_response is None:
        raise HTTPException(status_code=503, detail="CORE unavailable. Please try again later.")
    if "detail" in core_response:
        raise HTTPException(
            status_code=core_response.get("_status_code", 400),
            detail=core_response["detail"],
        )
    return core_response


@router.post("/verificar-email")
async def verificar_email_cliente(
        request: Request,
        usuario: dict = Depends(get_current_user_payload)
):
    body = await request.json()
    core_response = await core_client.post(
        "/api/v1/clientes/auth/verificar-email",
        json=body,
        headers={"Authorization": request.headers.get("Authorization", "")}
    )
    if core_response is None:
        raise HTTPException(status_code=503, detail="CORE unavailable. Please try again later.")
    if "detail" in core_response:
        raise HTTPException(
            status_code=core_response.get("_status_code", 400),
            detail=core_response["detail"],
        )
    return core_response


# ─── Actualizar perfil (nombre) ─────────────────────────────────────────────────

@router.put("/perfil")
async def actualizar_perfil_cliente(
        request: Request,
        db: Session = Depends(get_session),
        usuario: dict = Depends(get_current_user_payload)
):
    """Proxy al CORE. Actualiza el nombre del cliente. Sincroniza el caché local."""
    body = await request.json()
    core_response = await core_client.put(
        "/api/v1/clientes/auth/perfil",
        json=body,
        headers={"Authorization": request.headers.get("Authorization", "")}
    )
    if core_response is None:
        raise HTTPException(status_code=503, detail="CORE unavailable. Please try again later.")
    if "detail" in core_response:
        raise HTTPException(status_code=400, detail=core_response["detail"])

    # Sync local cache with the new name
    nuevo_nombre = core_response.get("nombre_completo")
    if nuevo_nombre:
        cliente_id = int(usuario.get("sub"))
        cliente_local = db.get(Cliente, cliente_id)
        if cliente_local:
            cliente_local.nombre_completo = nuevo_nombre
            db.add(cliente_local)
            db.commit()

    return core_response


# ─── Solicitar cambio de email ─────────────────────────────────────────────────

@router.post("/solicitar-cambio-email")
async def solicitar_cambio_email(
        request: Request,
        usuario: dict = Depends(get_current_user_payload)
):
    """Proxy al CORE. Inicia el flujo de cambio de email con doble confirmación."""
    body = await request.json()
    core_response = await core_client.post(
        "/api/v1/clientes/auth/solicitar-cambio-email",
        json=body,
        headers={"Authorization": request.headers.get("Authorization", "")}
    )
    if core_response is None:
        raise HTTPException(status_code=503, detail="CORE unavailable. Please try again later.")
    if "detail" in core_response:
        raise HTTPException(status_code=400, detail=core_response["detail"])
    return core_response


@router.post("/solicitar-cambio-email-otp")
async def solicitar_cambio_email_otp(
        request: Request,
        usuario: dict = Depends(get_current_user_payload)
):
    body = await request.json()
    core_response = await core_client.post(
        "/api/v1/clientes/auth/solicitar-cambio-email-otp",
        json=body,
        headers={"Authorization": request.headers.get("Authorization", "")}
    )
    if core_response is None:
        raise HTTPException(status_code=503, detail="CORE unavailable. Please try again later.")
    if "detail" in core_response:
        raise HTTPException(
            status_code=core_response.get("_status_code", 400),
            detail=core_response["detail"],
        )
    return core_response


# ─── Solicitar eliminación de cuenta ──────────────────────────────────────────

@router.post("/solicitar-eliminacion")
async def solicitar_eliminacion_cuenta(
        request: Request,
        usuario: dict = Depends(get_current_user_payload)
):
    """Proxy al CORE. Envía email de confirmación de eliminación de cuenta."""
    body = await request.json()
    core_response = await core_client.post(
        "/api/v1/clientes/auth/solicitar-eliminacion",
        json=body,
        headers={"Authorization": request.headers.get("Authorization", "")}
    )
    if core_response is None:
        raise HTTPException(status_code=503, detail="CORE unavailable. Please try again later.")
    if "detail" in core_response:
        raise HTTPException(status_code=400, detail=core_response["detail"])
    return core_response


# ─── Solicitar reactivación de cuenta ─────────────────────────────────────────

@router.post("/reactivar")
async def solicitar_reactivacion_cuenta(
        request: Request
):
    """Proxy al CORE. No requiere autenticación (la cuenta está inactiva)."""
    body = await request.json()
    core_response = await core_client.post("/api/v1/clientes/auth/reactivar", json=body)
    if core_response is None:
        raise HTTPException(status_code=503, detail="CORE unavailable. Please try again later.")
    return core_response


# ─── Confirmar cambio de email ────────────────────────────────────────────────

@router.post("/confirmar-cambio-email")
async def confirmar_cambio_email(
        request: Request
):
    body = await request.json()
    core_response = await core_client.post("/api/v1/clientes/auth/confirmar-cambio-email", json=body)
    if core_response is None:
        raise HTTPException(status_code=503, detail="CORE unavailable. Please try again later.")
    if "detail" in core_response:
        raise HTTPException(status_code=400, detail=core_response["detail"])
    return core_response


@router.post("/confirmar-cambio-email-otp")
async def confirmar_cambio_email_otp(
        request: Request,
        usuario: dict = Depends(get_current_user_payload)
):
    body = await request.json()
    core_response = await core_client.post(
        "/api/v1/clientes/auth/confirmar-cambio-email-otp",
        json=body,
        headers={"Authorization": request.headers.get("Authorization", "")}
    )
    if core_response is None:
        raise HTTPException(status_code=503, detail="CORE unavailable. Please try again later.")
    if "detail" in core_response:
        raise HTTPException(
            status_code=core_response.get("_status_code", 400),
            detail=core_response["detail"],
        )
    return core_response


# ─── Confirmar eliminación de cuenta ──────────────────────────────────────────

@router.post("/confirmar-eliminacion")
async def confirmar_eliminacion_cuenta(
        request: Request
):
    body = await request.json()
    core_response = await core_client.post("/api/v1/clientes/auth/confirmar-eliminacion", json=body)
    if core_response is None:
        raise HTTPException(status_code=503, detail="CORE unavailable. Please try again later.")
    if "detail" in core_response:
        raise HTTPException(status_code=400, detail=core_response["detail"])
    return core_response


# ─── Confirmar reactivación de cuenta ─────────────────────────────────────────

@router.post("/confirmar-reactivacion")
async def confirmar_reactivacion_cuenta(
        request: Request
):
    body = await request.json()
    core_response = await core_client.post("/api/v1/clientes/auth/confirmar-reactivacion", json=body)
    if core_response is None:
        raise HTTPException(status_code=503, detail="CORE unavailable. Please try again later.")
    if "detail" in core_response:
        raise HTTPException(status_code=400, detail=core_response["detail"])
    return core_response
