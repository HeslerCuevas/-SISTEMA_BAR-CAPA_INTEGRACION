from fastapi import APIRouter, Depends, Response
from sqlmodel import Session, select
from typing import List
import logging

from app.db.database import get_session
from app.clients.core_client import core_client
from app.models.integration_models import Producto
from app.schemas.auth_schemas import ProductoResponse
from app.api.deps import get_current_user_payload

logger = logging.getLogger("RouterProductos")
router = APIRouter(prefix="/productos", tags=["Catálogo de Productos"])


@router.get("/", response_model=List[ProductoResponse])
async def obtener_catalogo(
        response: Response,
        db: Session = Depends(get_session),
        # Esta línea exige que el usuario envíe un JWT válido para ver los productos
        usuario_actual: dict = Depends(get_current_user_payload)
):
    """
    Obtiene el catálogo de productos con Resiliencia Activa.
    Si el CORE falla, hace "Fallback" a la Caché Local de SQL Server.
    """
    logger.info(f"Usuario {usuario_actual.get('sub')} solicitando catálogo desde {usuario_actual.get('canal')}")

    # 1. INTENTAR HABLAR CON EL CORE
    # (Asumimos que el CORE tiene un endpoint GET /productos)
    core_data = await core_client.get("/productos/")

    # 2. EVALUAR LA RESPUESTA
    if core_data is not None:
        # ==========================================
        # ESCENARIO A: EL CORE ESTÁ ONLINE
        # ==========================================
        response.headers["X-Data-Source"] = "CORE"

        # OJO INGENIERO: En un entorno de producción 100% real, aquí llamarías a un
        # servicio como `cache_service.sincronizar(core_data)` para actualizar
        # tu tabla SQL Server local con los precios más nuevos.

        resultados = []
        for item in core_data:
            resultados.append(
                ProductoResponse(
                    id=item.get("id"),
                    nombre=item.get("nombre"),
                    precio_base=item.get("precio_base"),
                    cantidad_disponible=item.get("cantidad_disponible", 0),
                    origen_datos="CORE"  # Le avisamos al frontend de dónde vino
                )
            )
        return resultados

    else:
        # ==========================================
        # ESCENARIO B: EL CORE ESTÁ OFFLINE (FALLBACK)
        # ==========================================
        response.headers["X-Data-Source"] = "CACHE_LOCAL"
        logger.warning("Activando lectura de contingencia desde SQL Server Local.")

        # Hacemos la consulta a la base de datos local (Integration_Gateway_DB)
        statement = select(Producto).where(Producto.activo == True)
        productos_locales = db.exec(statement).all()

        resultados = []
        for prod in productos_locales:
            resultados.append(
                ProductoResponse(
                    id=prod.id,
                    nombre=prod.nombre,
                    precio_base=float(prod.precio_base),
                    cantidad_disponible=99,  # Un valor por defecto para contingencia
                    origen_datos="CACHE_LOCAL"  # El frontend sabrá que está en modo offline
                )
            )
        return resultados