"""
Promotion synchronization service for INTEGRATION layer.
Pulls promotion catalog from CORE, caches locally, and uploads audit records.
"""
import httpx
import logging
from datetime import datetime
from app.core.timezone import get_local_now
from decimal import Decimal
from typing import Optional
from sqlmodel import Session, select

from app.models.integration_models import PromocionCache, CodigoPromocionalCache, AplicacionPromocionOffline
from app.core.config import settings

logger = logging.getLogger("PromocionSyncService")

CORE_PROMO_URL = f"{settings.CORE_URL}/api/v1/promociones"
CORE_AUDIT_URL = f"{settings.CORE_URL}/api/v1/promociones/aplicaciones"


async def sincronizar_promociones_desde_core(db: Session, token: Optional[str] = None) -> dict:
    """
    Pull the full promotion catalog from CORE and upsert into Cache.Promociones.
    Also pulls eligibility info (etiqueta_identificador, requiere_identificador).
    Returns sync stats.
    """
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    stats = {"promociones": 0, "codigos": 0, "errores": 0}

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            # Pull all active promotions
            resp = await client.get(f"{CORE_PROMO_URL}/?solo_activas=false", headers=headers)
            if resp.status_code != 200:
                logger.warning(f"Promo sync failed: HTTP {resp.status_code}")
                return stats

            promociones = resp.json()

            # Pull eligibility config
            eleg_resp = await client.get(f"{CORE_PROMO_URL}/elegibilidad", headers=headers)
            eleg_map = {}
            if eleg_resp.status_code == 200:
                for e in eleg_resp.json():
                    eleg_map[e["promocion_id"]] = e

            for promo_data in promociones:
                try:
                    pid = promo_data.get("id")
                    if not pid:
                        continue

                    eleg = eleg_map.get(pid, {})
                    existing = db.get(PromocionCache, pid)
                    fecha_inicio = _parse_dt(promo_data.get("fecha_inicio"))
                    fecha_fin = _parse_dt(promo_data.get("fecha_fin"))

                    if existing:
                        existing.nombre = promo_data.get("nombre", existing.nombre)
                        existing.tipo_aplicacion = promo_data.get("tipo_aplicacion", "AUTOMATICA")
                        existing.tipo_descuento = promo_data.get("tipo_descuento", existing.tipo_descuento)
                        existing.valor = Decimal(str(promo_data.get("valor", existing.valor)))
                        existing.aplica_a = promo_data.get("aplica_a", "TODOS")
                        existing.aplica_happy_hour = promo_data.get("aplica_happy_hour", False)
                        existing.hora_inicio_hh = promo_data.get("hora_inicio_hh")
                        existing.hora_fin_hh = promo_data.get("hora_fin_hh")
                        existing.fecha_inicio = fecha_inicio or existing.fecha_inicio
                        existing.fecha_fin = fecha_fin
                        existing.activo = promo_data.get("activo", True)
                        existing.prioridad = promo_data.get("prioridad", 0)
                        existing.etiqueta_identificador = eleg.get("etiqueta_identificador")
                        existing.requiere_identificador = eleg.get("requiere_identificador", True)
                        pmf = promo_data.get("precio_minimo_final")
                        existing.precio_minimo_final = Decimal(str(pmf)) if pmf is not None else None
                        existing.ultima_sincronizacion = get_local_now()
                        db.add(existing)
                    else:
                        pmf = promo_data.get("precio_minimo_final")
                        obj = PromocionCache(
                            id=pid,
                            nombre=promo_data.get("nombre", ""),
                            tipo_aplicacion=promo_data.get("tipo_aplicacion", "AUTOMATICA"),
                            tipo_descuento=promo_data.get("tipo_descuento", "PORCENTAJE"),
                            valor=Decimal(str(promo_data.get("valor", 0))),
                            aplica_a=promo_data.get("aplica_a", "TODOS"),
                            aplica_happy_hour=promo_data.get("aplica_happy_hour", False),
                            hora_inicio_hh=promo_data.get("hora_inicio_hh"),
                            hora_fin_hh=promo_data.get("hora_fin_hh"),
                            fecha_inicio=fecha_inicio or get_local_now(),
                            fecha_fin=fecha_fin,
                            activo=promo_data.get("activo", True),
                            prioridad=promo_data.get("prioridad", 0),
                            etiqueta_identificador=eleg.get("etiqueta_identificador"),
                            requiere_identificador=eleg.get("requiere_identificador", True),
                            precio_minimo_final=Decimal(str(pmf)) if pmf is not None else None,
                        )
                        db.add(obj)
                    stats["promociones"] += 1
                except Exception as e:
                    logger.error(f"Error syncing promo {promo_data.get('id')}: {e}")
                    stats["errores"] += 1

            # Fetch promo codes
            codigos_resp = await client.get(f"{CORE_PROMO_URL}/codigos", headers=headers)
            if codigos_resp.status_code == 200:
                for c_data in codigos_resp.json():
                    try:
                        cid = c_data.get("id")
                        c_exist = db.get(CodigoPromocionalCache, cid)
                        if c_exist:
                            c_exist.codigo = c_data.get("codigo", c_exist.codigo)
                            c_exist.promocion_id = c_data.get("promocion_id")
                            c_exist.activo = c_data.get("activo", True)
                            c_exist.usos_maximos = c_data.get("usos_maximos")
                            c_exist.usos_actuales = c_data.get("usos_actuales", 0)
                            c_exist.ultima_sincronizacion = get_local_now()
                            db.add(c_exist)
                        else:
                            c_obj = CodigoPromocionalCache(
                                id=cid,
                                codigo=c_data.get("codigo", ""),
                                promocion_id=c_data.get("promocion_id"),
                                activo=c_data.get("activo", True),
                                usos_maximos=c_data.get("usos_maximos"),
                                usos_actuales=c_data.get("usos_actuales", 0)
                            )
                            db.add(c_obj)
                        stats["codigos"] += 1
                    except Exception as e:
                        logger.error(f"Error syncing codigo {c_data.get('codigo')}: {e}")
                        stats["errores"] += 1

        db.commit()

    except Exception as e:
        logger.error(f"Promotion sync connection error: {e}")
        stats["errores"] += 1

    return stats


async def subir_auditorias_pendientes(db: Session, token: Optional[str] = None) -> dict:
    """
    Upload pending promotion audit records to CORE.
    Uses outbox pattern — marks records COMPLETADO on success, increments retries on failure.
    """
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    pendientes = db.exec(
        select(AplicacionPromocionOffline)
        .where(
            AplicacionPromocionOffline.estado_sincronizacion == "PENDIENTE",
            AplicacionPromocionOffline.intentos_sincronizacion < 5
        )
        .limit(50)
    ).all()

    exitos = 0
    errores = 0

    async with httpx.AsyncClient(timeout=10.0) as client:
        for record in pendientes:
            try:
                payload = {
                    "promocion_id": record.promocion_id,
                    "nombre_promocion_snap": record.nombre_promocion_snap,
                    "tipo_aplicacion": record.tipo_aplicacion,
                    "factura_uuid": str(record.factura_uuid) if record.factura_uuid else None,
                    "empleado_id": record.empleado_id,
                    "empleado_autorizador_id": record.empleado_autorizador_id,
                    "cliente_id": record.cliente_id,
                    "identificador_capturado": record.identificador_capturado,
                    "monto_descuento": float(record.monto_descuento),
                    "terminal": record.terminal,
                    "notas": record.notas,
                }
                resp = await client.post(CORE_AUDIT_URL, headers=headers, json=payload)
                if resp.status_code in (200, 201):
                    record.estado_sincronizacion = "COMPLETADO"
                    exitos += 1
                else:
                    record.intentos_sincronizacion += 1
                    record.ultimo_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
                    errores += 1
            except Exception as e:
                record.intentos_sincronizacion += 1
                record.ultimo_error = str(e)[:500]
                errores += 1
            db.add(record)

    db.commit()
    return {"exitos": exitos, "errores": errores, "pendientes_procesados": len(pendientes)}


def _parse_dt(val) -> Optional[datetime]:
    if not val:
        return None
    try:
        if isinstance(val, datetime):
            return val
        return datetime.fromisoformat(str(val).replace("Z", "+00:00").replace("+00:00", ""))
    except Exception:
        return None

async def subir_sesiones_supervisor_pendientes(db: Session, token: Optional[str] = None) -> dict:
    """
    Upload pending supervisor session records to CORE.
    """
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    from app.models.integration_models import SupervisorSessionOffline
    pendientes = db.exec(
        select(SupervisorSessionOffline)
        .where(
            SupervisorSessionOffline.estado_sincronizacion == "PENDIENTE",
            SupervisorSessionOffline.intentos_sincronizacion < 5
        )
        .limit(50)
    ).all()

    if not pendientes:
        return {"exitos": 0, "errores": 0, "pendientes_procesados": 0}

    exitos = 0
    errores = 0

    payload = []
    for record in pendientes:
        payload.append({
            "id": str(record.id),
            "supervisor_id": record.supervisor_id,
            "cajero_id": record.cajero_id,
            "terminal": record.terminal,
            "inicio": record.inicio.isoformat(),
            "fin": record.fin.isoformat(),
            "motivo_fin": record.motivo_fin
        })

    url = f"{settings.CORE_URL}/api/v1/promociones/supervisor/sessions/sync"
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code in (200, 201):
                for record in pendientes:
                    record.estado_sincronizacion = "COMPLETADO"
                    exitos += 1
            else:
                for record in pendientes:
                    record.intentos_sincronizacion += 1
                    record.ultimo_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
                    errores += 1
        except Exception as e:
            for record in pendientes:
                record.intentos_sincronizacion += 1
                record.ultimo_error = str(e)[:500]
                errores += 1

    db.commit()
    return {"exitos": exitos, "errores": errores, "pendientes_procesados": len(pendientes)}
