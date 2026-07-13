import logging
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlmodel import Session

from app.db.database import get_session
from app.clients.core_client import core_client

logger = logging.getLogger("RouterPromociones")
router = APIRouter(prefix="/promociones", tags=["Promociones y Descuentos"])


# ─── Evaluar promociones de un item ───────────────────────────────────────────

@router.get("/")
async def listar_promociones(
        response: Response,
        db: Session = Depends(get_session)
):
    """
    Returns the complete catalog of active promotions.
    Tries CORE first; falls back to local Cache if offline.
    """
    core_data = await core_client.get("/api/v1/promociones/?solo_activas=false")
    
    if core_data is not None:
        response.headers["X-Data-Source"] = "CORE"
        return core_data
        
    # Fallback
    response.headers["X-Data-Source"] = "CACHE_LOCAL"
    from sqlmodel import select
    from app.models.integration_models import PromocionCache
    
    stmt = select(PromocionCache)
    promos = db.exec(stmt).all()
    # Serialize for fallback (CAJA_NEW handles missing array fields if they are offline)
    result = []
    for p in promos:
        p_dict = p.model_dump()
        p_dict["producto_ids"] = []
        p_dict["categoria_ids"] = []
        result.append(p_dict)
    return result

@router.get("/evaluar/item")
async def evaluar_promociones_item(
        producto_id: int = Query(...),
        categoria_id: int = Query(...),
        subtotal: float = Query(..., gt=0),
):
    """
    Returns all active promotions that apply to a specific product/category.
    Used by both the Mobile App and POS when building an order to check discounts.
    Pure proxy to CORE — no local fallback (promotions require real-time data).
    """
    core_response = await core_client.get(
        "/api/v1/promociones/evaluar/item",
        params={"producto_id": producto_id, "categoria_id": categoria_id, "subtotal": subtotal}
    )
    if core_response is None:
        logger.warning("[PROMOCIONES] CORE no disponible. No se pueden evaluar promociones.")
        return []  # Graceful degradation: no discount applied rather than blocking the sale
    return core_response


# ─── Evaluar mejor descuento ──────────────────────────────────────────────────

@router.get("/evaluar/mejor-descuento")
async def evaluar_mejor_descuento(
        producto_id: int = Query(...),
        categoria_id: int = Query(...),
        subtotal: float = Query(..., gt=0),
):
    """
    Returns only the single best promotion for a product.
    Used when the UI wants to display one clear discount badge.
    """
    core_response = await core_client.get(
        "/api/v1/promociones/evaluar/mejor-descuento",
        params={"producto_id": producto_id, "categoria_id": categoria_id, "subtotal": subtotal}
    )
    if core_response is None:
        return None  # Graceful: no best discount when CORE is offline
    return core_response


# ─── Evaluar descuentos globales ──────────────────────────────────────────────

@router.get("/evaluar/globales")
async def evaluar_descuentos_globales(
        subtotal_total: float = Query(..., gt=0),
):
    """
    Returns promotions that apply to the entire order total (not per item).
    Called at checkout to compute final order discounts.
    """
    core_response = await core_client.get(
        "/api/v1/promociones/evaluar/globales",
        params={"subtotal_total": subtotal_total}
    )
    if core_response is None:
        return []  # Graceful: skip global discounts when CORE unreachable
    return core_response


# ─── Estado Happy Hour ─────────────────────────────────────────────────────────

@router.get("/happy-hour/activo")
async def verificar_happy_hour_activo():
    """
    Checks if any Happy Hour promotion is currently active.
    Both Mobile App and POS poll this to trigger UI changes (e.g. banner, colored prices).
    Returns a safe default (inactive) when CORE is unreachable so the UI degrades gracefully.
    """
    core_response = await core_client.get("/api/v1/promociones/happy-hour/activo")
    if core_response is None:
        logger.warning("[HAPPY-HOUR] CORE no disponible. Retornando estado inactivo por defecto.")
        return {
            "happy_hour_activo": False,
            "hora_actual": "N/A",
            "promociones_activas": [],
            "fuente": "FALLBACK_OFFLINE"
        }
    core_response["fuente"] = "CORE"
    return core_response


# ─── Promotion System Redesign Endpoints ──────────────────────────────────────

@router.get("/elegibilidad")
def listar_promociones_elegibilidad(db: Session = Depends(get_session)):
    """Return all active eligibility promotions from local Cache."""
    from app.models.integration_models import PromocionCache
    from sqlmodel import select
    stmt = select(PromocionCache).where(
        PromocionCache.activo == True,
        PromocionCache.tipo_aplicacion == "ELEGIBILIDAD"
    )
    return db.exec(stmt).all()


@router.post("/codigos/validar")
async def validar_codigo_promo(
    codigo: str = Query(...),
    subtotal: float = Query(...),
    cliente_id: int = Query(None),
    db: Session = Depends(get_session)
):
    """
    Validate a promo code. Tries CORE first. If offline, falls back to local cache.
    """
    from app.core.timezone import get_local_now
    import traceback
    
    # Try CORE first
    try:
        core_resp = await core_client.post(
            "/api/v1/promociones/codigos/validar",
            json={"codigo": codigo, "subtotal": subtotal, "cliente_id": cliente_id}
        )
        if core_resp is not None:
            return core_resp
    except Exception as e:
        logger.warning(f"Error validating code with CORE, falling back to cache: {e}")

    # Fallback to local cache
    logger.info("CORE offline for promo validation, using local cache.")
    from app.models.integration_models import CodigoPromocionalCache, PromocionCache
    from sqlmodel import select
    from decimal import Decimal

    ahora = get_local_now()
    stmt = select(CodigoPromocionalCache).where(
        CodigoPromocionalCache.codigo == codigo.strip().upper(),
        CodigoPromocionalCache.activo == True
    )
    codigo_obj = db.exec(stmt).first()
    
    if not codigo_obj:
        return {"valido": False, "error": "Código no encontrado o inactivo (offline cache)."}
        
    if codigo_obj.fecha_fin and codigo_obj.fecha_fin < ahora:
        return {"valido": False, "error": "Código expirado."}
    if codigo_obj.fecha_inicio > ahora:
        return {"valido": False, "error": "Código aún no vigente."}
    if codigo_obj.uso_maximo is not None and codigo_obj.usos_actuales >= codigo_obj.uso_maximo:
        return {"valido": False, "error": "Límite de usos alcanzado."}
        
    promo = db.get(PromocionCache, codigo_obj.promocion_id)
    if not promo or not promo.activo:
        return {"valido": False, "error": "Promoción asociada inactiva."}

    # Calculate offline amount manually
    monto = Decimal("0")
    if promo.tipo_descuento == 'PORCENTAJE':
        monto = Decimal(str(subtotal)) * promo.valor / Decimal("100")
    else:
        monto = min(promo.valor, Decimal(str(subtotal)))

    return {
        "valido": True,
        "codigo_id": codigo_obj.id,
        "promocion_id": promo.id,
        "nombre": promo.nombre,
        "tipo_descuento": promo.tipo_descuento,
        "valor": float(promo.valor),
        "tipo_aplicacion": "CODIGO_PROMO",
        "monto": float(monto)
    }


@router.post("/supervisor/auth")
async def autenticar_supervisor(
    email: str = Query(...),
    otp: str = Query(...)
):
    """Proxy supervisor TOTP auth to CORE. Fails if CORE is offline."""
    core_resp = await core_client.post(
        "/api/v1/promociones/supervisor/auth",
        json={"email": email, "otp": otp}
    )
    if core_resp is None:
        raise HTTPException(
            status_code=503, 
            detail="No se puede contactar a CORE para autorizar. El sistema debe estar en línea."
        )
    # Forward errors transparently
    return core_resp


@router.post("/aplicaciones")
def registrar_aplicacion_promocion(
    payload: dict,
    db: Session = Depends(get_session)
):
    """
    POS reports a promotion application.
    Always saved to offline queue first, then async sync is triggered.
    """
    import uuid as _uuid
    from app.models.integration_models import AplicacionPromocionOffline
    
    factura_uuid = None
    raw = payload.get("factura_uuid")
    if raw:
        try:
            factura_uuid = _uuid.UUID(str(raw))
        except Exception:
            pass

    record = AplicacionPromocionOffline(
        promocion_id=payload.get("promocion_id"),
        nombre_promocion_snap=payload.get("nombre_promocion_snap", ""),
        tipo_aplicacion=payload.get("tipo_aplicacion", "AUTOMATICA"),
        factura_uuid=factura_uuid,
        empleado_id=payload.get("empleado_id"),
        empleado_autorizador_id=payload.get("empleado_autorizador_id"),
        cliente_id=payload.get("cliente_id"),
        identificador_capturado=payload.get("identificador_capturado"),
        monto_descuento=payload.get("monto_descuento", 0),
        terminal=payload.get("terminal"),
        notas=payload.get("notas"),
    )
    db.add(record)
    db.commit()
    
    # Try pushing pending records (including this one) immediately
    from app.services.promocion_sync_service import subir_auditorias_pendientes
    subir_auditorias_pendientes(db)
    
    return {"ok": True, "offline_id": str(record.id)}


@router.get("/sync")
def trigger_promociones_sync(db: Session = Depends(get_session)):
    """Trigger a sync of promotions and promo codes from CORE."""
    from app.services.promocion_sync_service import sincronizar_promociones_desde_core
    return sincronizar_promociones_desde_core(db)

@router.post("/supervisor/sessions/sync")
async def recibir_sesiones_supervisor(
    sesiones: list[dict],
    db: Session = Depends(get_session)
):
    """
    Receives supervisor sessions and stores them in the offline queue for async sync to CORE.
    """
    import uuid as _uuid
    from datetime import datetime
    from app.models.integration_models import SupervisorSessionOffline
    from app.services.promocion_sync_service import subir_sesiones_supervisor_pendientes
    
    for sess in sesiones:
        try:
            record_id = _uuid.UUID(str(sess.get("id")))
        except Exception:
            record_id = _uuid.uuid4()
            
        record = SupervisorSessionOffline(
            id=record_id,
            supervisor_id=sess["supervisor_id"],
            cajero_id=sess["cajero_id"],
            terminal=sess["terminal"],
            inicio=datetime.fromisoformat(sess["inicio"]) if isinstance(sess["inicio"], str) else sess["inicio"],
            fin=datetime.fromisoformat(sess["fin"]) if isinstance(sess["fin"], str) else sess["fin"],
            motivo_fin=sess["motivo_fin"],
            estado_sincronizacion="PENDIENTE",
            intentos_sincronizacion=0
        )
        db.add(record)
    
    db.commit()
    
    # Try pushing pending records immediately
    await subir_sesiones_supervisor_pendientes(db)
    
    return {"ok": True, "recibidas": len(sesiones)}
