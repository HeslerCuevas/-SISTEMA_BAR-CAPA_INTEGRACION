from fastapi import APIRouter, Depends, Response, BackgroundTasks
from sqlmodel import Session, select
from typing import List
import logging
from app.core.timezone import get_local_now

from app.db.database import get_session, engine
from app.clients.core_client import core_client
from app.models.integration_models import Producto, InventarioLocal, Categoria, Impuesto
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
                cat_id = item.get("categoria_id")
                imp_id = item.get("impuesto_id")

                if cat_id:
                    cat_local = db_background.get(Categoria, cat_id)
                    if not cat_local:
                        db_background.add(Categoria(id=cat_id, nombre="Cat. Sincronizada"))
                        db_background.commit()

                if imp_id:
                    imp_local = db_background.get(Impuesto, imp_id)
                    if not imp_local:
                        db_background.add(Impuesto(id=imp_id, nombre="Imp. Sincronizado", tasa_porcentaje=18.0))
                        db_background.commit()

                prod_local = db_background.exec(
                    select(Producto).where(Producto.id == item.get("id"))
                ).first()

                # CORE now uses tipo_control_inventario instead of es_inventariable
                tipo_control = item.get("tipo_control_inventario", "PRODUCTO")

                if prod_local:
                    prod_local.sku = item.get("sku", prod_local.sku)
                    prod_local.nombre = item.get("nombre")
                    prod_local.precio_base = item.get("precio_base")
                    prod_local.tipo_control_inventario = tipo_control
                    prod_local.imagen_url = item.get("imagen_url")
                    prod_local.categoria_id = cat_id if cat_id else prod_local.categoria_id
                    prod_local.impuesto_id = imp_id if imp_id else prod_local.impuesto_id
                    db_background.add(prod_local)
                    prod_actualizados += 1
                else:
                    nuevo_prod = Producto(
                        id=item.get("id"),
                        categoria_id=cat_id if cat_id else 1,
                        impuesto_id=imp_id if imp_id else 1,
                        sku=item.get("sku", "N/A"),
                        nombre=item.get("nombre"),
                        precio_base=item.get("precio_base"),
                        imagen_url=item.get("imagen_url"),
                        tipo_control_inventario=tipo_control,
                    )
                    db_background.add(nuevo_prod)
                    prod_nuevos += 1

                # Inventariable when tipo_control_inventario is PRODUCTO or INGREDIENTES (not NINGUNO)
                if item.get("tipo_control_inventario", "PRODUCTO") != "NINGUNO":
                    inv_local = db_background.exec(
                        select(InventarioLocal).where(
                            InventarioLocal.producto_id == item.get("id"),
                            InventarioLocal.sucursal_id == settings.SUCURSAL_ID
                        )
                    ).first()

                    stock_fresco = item.get("cantidad_disponible", 0)

                    if inv_local:
                        inv_local.cantidad_disponible = stock_fresco
                        inv_local.ultima_sincronizacion = get_local_now()
                        db_background.add(inv_local)
                        inv_actualizados += 1
                    else:
                        nuevo_inv = InventarioLocal(
                            producto_id=item.get("id"),
                            sucursal_id=settings.SUCURSAL_ID,
                            cantidad_disponible=stock_fresco,
                            ultima_sincronizacion=get_local_now()
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

    core_data = await core_client.get("/api/v1/productos/categorias")

    if core_data is not None:
        response.headers["X-Data-Source"] = "CORE"
        background_tasks.add_task(sincronizar_cache_categorias, core_data)

        return [
            CategoriaResponse(
                id=item.get("id"),
                nombre=item.get("nombre"),
                descripcion=item.get("descripcion", ""),
                activo=item.get("activo", True)
            ) for item in core_data
        ]
    else:
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
    logger.info(f"Solicitando productos de cat {categoria_id} (Acceso Público)")

    core_data = await core_client.get(f"/api/v1/productos/por-categoria/{categoria_id}")

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
                    imagen_url=item.get("imagen_url"),
                    id_categoria=item.get("categoria_id")
                )
            )
        return resultados
    else:
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
                    cantidad_disponible=99,
                    origen_datos="CACHE_LOCAL",
                    imagen_url=prod.imagen_url,
                    id_categoria=prod.categoria_id
                )
            )
        return resultados


@router.get("/", response_model=List[ProductoResponse])
async def obtener_catalogo(
        response: Response,
        background_tasks: BackgroundTasks,
        db: Session = Depends(get_session)
):
    logger.info("Solicitando catálogo completo (Acceso Público)")

    core_data = await core_client.get("/api/v1/productos/")

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
                    imagen_url=item.get("imagen_url"),
                    id_categoria=item.get("categoria_id")
                )
            )
        return resultados

    else:
        response.headers["X-Data-Source"] = "CACHE_LOCAL"
        logger.warning("[FALLBACK] CORE inaccesible. Sirviendo catálogo desde SQL Server Local.")

        statement = select(Producto)
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
                    imagen_url=prod.imagen_url,
                    id_categoria=prod.categoria_id
                )
            )
        return resultados


# ─── GET single product (POS: stock check before adding to order) ─────────────

@router.get("/{producto_id}", response_model=ProductoResponse)
async def obtener_producto(
        producto_id: int,
        response: Response,
        db: Session = Depends(get_session)
):
    """Returns a single product. Tries CORE first; falls back to local cache."""
    core_data = await core_client.get(f"/api/v1/productos/{producto_id}")

    if core_data is not None and "detail" not in core_data:
        response.headers["X-Data-Source"] = "CORE"
        return ProductoResponse(
            id=core_data.get("id"),
            nombre=core_data.get("nombre"),
            precio_base=core_data.get("precio_base"),
            cantidad_disponible=core_data.get("cantidad_disponible", 0),
            origen_datos="CORE",
            imagen_url=core_data.get("imagen_url"),
            id_categoria=core_data.get("categoria_id")
        )

    response.headers["X-Data-Source"] = "CACHE_LOCAL"
    prod_local = db.get(Producto, producto_id)
    if not prod_local:
        raise HTTPException(status_code=404, detail="Producto no encontrado.")

    return ProductoResponse(
        id=prod_local.id,
        nombre=prod_local.nombre,
        precio_base=float(prod_local.precio_base),
        cantidad_disponible=99,
        origen_datos="CACHE_LOCAL",
        imagen_url=prod_local.imagen_url,
        id_categoria=prod_local.categoria_id
    )