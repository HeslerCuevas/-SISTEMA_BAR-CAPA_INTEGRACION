import asyncio
import logging
from sqlmodel import Session
from app.db.database import engine
from app.services.cache_service import sincronizar_personal_desde_core, sincronizar_productos_desde_core
from app.services.promocion_sync_service import sincronizar_promociones_desde_core, subir_auditorias_pendientes, subir_sesiones_supervisor_pendientes

logger = logging.getLogger("BackgroundSync")


async def auto_sync_worker():
    logger.info("Iniciando Worker de Sincronización Automática (Intervalo: 5s)")

    while True:
        try:
            with Session(engine) as session:
                await sincronizar_personal_desde_core(session)
                await sincronizar_productos_desde_core(session)
                await sincronizar_promociones_desde_core(session)
                await subir_auditorias_pendientes(session)
                await subir_sesiones_supervisor_pendientes(session)
        except Exception as e:
            logger.error(f"Error en el ciclo de auto-sync: {e}")

        await asyncio.sleep(10)