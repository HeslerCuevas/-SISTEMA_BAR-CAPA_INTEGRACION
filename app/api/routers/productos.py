from fastapi import APIRouter, Depends, Response, BackgroundTasks
from sqlmodel import Session, select
from typing import List
import logging
from datetime import datetime

from app.db.database import get_session, engine
from app.clients.core_client import core_client
from app.models.integration_models import Producto, InventarioLocal, Categoria
from app.schemas.productos_schema import ProductoResponse, CategoriaResponse
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
                    prod_local.imagen_url = item.get("imagen_url")
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
                        imagen_url=item.get("imagen_url"),
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


def sincronizar_cache_categorias(core_data: list):
    with Session(engine) as db_background:
        try:
            cat_nuevas = 0
            cat_actualizadas = 0

            for item in core_data:
                cat_local = db_background.exec(
                    select(Categoria).where(Categoria.id == item.get("id"))
                ).first()

                if cat_local:
                    cat_local.nombre = item.get("nombre")
                    db_background.add(cat_local)
                    cat_actualizadas += 1
                else:
                    nueva_cat = Categoria(
                        id=item.get("id"),
                        nombre=item.get("nombre")
                    )
                    db_background.add(nueva_cat)
                    cat_nuevas += 1

            db_background.commit()
            logger.info(f"[CACHE REFRESH] Sincronización exitosa. Categorias (N:{cat_nuevas}, A:{cat_actualizadas})")

        except Exception as e:
            logger.error(f"[ERROR CACHE] Falló la sincronización de categorías: {str(e)}")
            db_background.rollback()


@router.get("/categorias", response_model=List[CategoriaResponse])
async def obtener_categorias(
        response: Response,
        background_tasks: BackgroundTasks,
        db: Session = Depends(get_session)
):
    logger.info("Solicitando categorias de menú (Acceso Público)")

    # 1. Intentar obtener desde el CORE
    core_data = await core_client.get("/productos/categorias")

    if core_data is not None:
        response.headers["X-Data-Source"] = "CORE"
        # 2. Sincronizar localmente en background
        background_tasks.add_task(sincronizar_cache_categorias, core_data)

        # Mapeamos la respuesta del CORE al esquema esperado
        return [
            CategoriaResponse(
                id=item.get("id"),
                nombre=item.get("nombre"),
                descripcion=item.get("descripcion", ""),
                activo=item.get("activo", True)
            ) for item in core_data
        ]
    else:
        # 3. Fallback: El CORE está caído, respondemos con SQL Server Local
        response.headers["X-Data-Source"] = "CACHE_LOCAL"
        logger.warning("[FALLBACK] CORE inaccesible. Sirviendo categorías desde SQL Server Local.")

        statement = select(Categoria)
        categorias_locales = db.exec(statement).all()

        return [
            CategoriaResponse(
                id=cat.id,
                nombre=cat.nombre,
                descripcion="Categoría Local",
                activo=True
            ) for cat in categorias_locales
        ]


@router.get("/por-categoria/{categoria_id}", response_model=List[ProductoResponse])
async def obtener_productos_por_categoria(
        categoria_id: int,
        response: Response,
        background_tasks: BackgroundTasks,
        db: Session = Depends(get_session)
):
    """Obtiene productos filtrados: Intenta ir al CORE, si falla usa la caché local"""
    logger.info(f"Solicitando productos de cat {categoria_id} (Acceso Público)")

    # 1. Intentar obtener desde el CORE
    core_data = await core_client.get(f"/productos/por-categoria/{categoria_id}")

    if core_data is not None:
        response.headers["X-Data-Source"] = "CORE"

        # Reutilizamos tu función maestra de sincronización de productos!
        background_tasks.add_task(sincronizar_cache_productos, core_data)

        resultados = []
        for item in core_data:
            resultados.append(
                ProductoResponse(
                    id=item.get("id"),
                    nombre=item.get("nombre"),
                    precio_base=item.get("precio_base"),
                    cantidad_disponible=item.get("cantidad_disponible", 0),
                    origen_datos="CORE",
                    imagen_url = item.get("imagen_url")
                )
            )
        return resultados
    else:
        # 2. Fallback: CORE caído, buscar en caché local
        response.headers["X-Data-Source"] = "CACHE_LOCAL"
        logger.warning(f"[FALLBACK] CORE inaccesible. Sirviendo productos cat {categoria_id} desde Local.")

        statement = select(Producto).where(Producto.categoria_id == categoria_id)
        productos_locales = db.exec(statement).all()

        resultados = []
        for prod in productos_locales:
            resultados.append(
                ProductoResponse(
                    id=prod.id,
                    nombre=prod.nombre,
                    precio_base=float(prod.precio_base),
                    cantidad_disponible=99,  # Al no tener CORE, asumimos stock
                    origen_datos="CACHE_LOCAL"
                )
            )
        return resultados


@router.get("/", response_model=List[ProductoResponse])
async def obtener_catalogo(
        response: Response,
        background_tasks: BackgroundTasks,
        db: Session = Depends(get_session)
):
    """Tu endpoint original intacto."""
    logger.info("Solicitando catálogo completo (Acceso Público)")

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
                    origen_datos="CORE",
                    imagen_url=item.get("imagen_url")
                )
            )
        return resultados

    else:
        response.headers["X-Data-Source"] = "CACHE_LOCAL"
        logger.warning("[FALLBACK] CORE inaccesible. Sirviendo catálogo desde SQL Server Local.")

        statement = select(Producto)  # Removido el filtro activo==True si no está en tu modelo local
        productos_locales = db.exec(statement).all()

        resultados = []
        for prod in productos_locales:
            resultados.append(
                ProductoResponse(
                    id=prod.id,
                    nombre=prod.nombre,
                    precio_base=float(prod.precio_base),
                    cantidad_disponible=99,
                    origen_datos="CACHE_LOCAL",
                    imagen_url=prod.imagen_url
                )
            )
        return resultados