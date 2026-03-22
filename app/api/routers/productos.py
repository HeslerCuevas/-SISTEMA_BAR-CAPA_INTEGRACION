from fastapi import APIRouter, Depends, Response, BackgroundTasks
from sqlmodel import Session, select
from typing import List
import logging
from datetime import datetime

from app.db.database import get_session, engine
from app.clients.core_client import core_client
from app.models.integration_models import Producto, InventarioLocal
from app.schemas.auth_schemas import ProductoResponse
from app.api.deps import get_current_user_payload
from app.core.config import settings

logger = logging.getLogger("RouterProductos")
router = APIRouter(prefix="/productos", tags=["Catálogo de Productos"])


def sincronizar_cache_productos(core_data: list):
    with Session(engine) as db_background:
        try:
            prod_nuevos = 0
            prod_actualizados = 0
            inv_nuevos = 0
            inv_actualizados = 0

            for item in core_data:
                prod_local = db_background.exec(
                    select(Producto).where(Producto.id == item.get("id"))
                ).first()

                if prod_local:
                    prod_local.sku = item.get("sku", prod_local.sku)
                    prod_local.nombre = item.get("nombre")
                    prod_local.precio_base = item.get("precio_base")
                    prod_local.es_inventariable = item.get("es_inventariable", True)
                    db_background.add(prod_local)
                    prod_actualizados += 1
                else:
                    nuevo_prod = Producto(
                        id=item.get("id"),
                        categoria_id=item.get("categoria_id", 1),
                        impuesto_id=item.get("impuesto_id", 1),
                        sku=item.get("sku", "N/A"),
                        nombre=item.get("nombre"),
                        precio_base=item.get("precio_base"),
                        es_inventariable=item.get("es_inventariable", True),
                    )
                    db_background.add(nuevo_prod)
                    prod_nuevos += 1

                if item.get("es_inventariable", True):

                    inv_local = db_background.exec(
                        select(InventarioLocal).where(
                            InventarioLocal.producto_id == item.get("id"),
                            InventarioLocal.sucursal_id == settings.SUCURSAL_ID
                        )
                    ).first()

                    stock_fresco = item.get("cantidad_disponible", 0)

                    if inv_local:
                        inv_local.cantidad_disponible = stock_fresco
                        inv_local.ultima_sincronizacion = datetime.utcnow()
                        db_background.add(inv_local)
                        inv_actualizados += 1
                    else:
                        nuevo_inv = InventarioLocal(
                            producto_id=item.get("id"),
                            sucursal_id=settings.SUCURSAL_ID,
                            cantidad_disponible=stock_fresco,
                            ultima_sincronizacion=datetime.utcnow()
                        )
                        db_background.add(nuevo_inv)
                        inv_nuevos += 1

            db_background.commit()
            logger.info(
                f"[CACHE REFRESH] Sincronización exitosa. Productos (N:{prod_nuevos}, A:{prod_actualizados}) | Inventario (N:{inv_nuevos}, A:{inv_actualizados})")

        except Exception as e:
            logger.error(f"[ERROR CACHE] Falló la sincronización doble: {str(e)}")
            db_background.rollback()


@router.get("/", response_model=List[ProductoResponse])
async def obtener_catalogo(
        response: Response,
        background_tasks: BackgroundTasks,
        db: Session = Depends(get_session),
        usuario_actual: dict = Depends(get_current_user_payload)
):
    logger.info(f"Usuario {usuario_actual.get('sub')} solicitando catálogo desde {usuario_actual.get('canal')}")

    core_data = await core_client.get("/productos/")

    if core_data is not None:
        response.headers["X-Data-Source"] = "CORE"

        background_tasks.add_task(sincronizar_cache_productos, core_data)

        resultados = []
        for item in core_data:
            resultados.append(
                ProductoResponse(
                    id=item.get("id"),
                    nombre=item.get("nombre"),
                    precio_base=item.get("precio_base"),
                    cantidad_disponible=item.get("cantidad_disponible", 0),
                    origen_datos="CORE"
                )
            )
        return resultados

    else:
        response.headers["X-Data-Source"] = "CACHE_LOCAL"
        logger.warning("[FALLBACK] CORE inaccesible. Sirviendo catálogo desde SQL Server Local.")

        statement = select(Producto).where(Producto.activo == True)
        productos_locales = db.exec(statement).all()

        resultados = []
        for prod in productos_locales:
            resultados.append(
                ProductoResponse(
                    id=prod.id,
                    nombre=prod.nombre,
                    precio_base=float(prod.precio_base),
                    cantidad_disponible=99,  # Al no tener el CORE, asumimos stock para no bloquear ventas
                    origen_datos="CACHE_LOCAL"
                )
            )
        return resultados