from fastapi import APIRouter, Depends
from sqlalchemy import Date
from sqlmodel import Session, select, func, desc
from datetime import date
from typing import Dict, Any

from app.db.database import get_session
from app.clients.core_client import core_client
from app.core.config import settings

from app.models.integration_models import PedidoOffline, DetallePedidoOffline, Producto, InventarioLocal

router = APIRouter(prefix="/reportes", tags=["Reportes y Dashboards"])


@router.get("/ventas-hoy")
async def get_ventas_hoy(db: Session = Depends(get_session)) -> Dict[str, Any]:
    reporte_core = await core_client.get("/reportes/ventas-hoy")

    if reporte_core:
        reporte_core["origen"] = "CORE"
        return reporte_core

    statement = select(
        func.sum(PedidoOffline.subtotal),
        func.sum(PedidoOffline.total_impuestos),
        func.sum(PedidoOffline.propina_legal),
        func.sum(PedidoOffline.total_general),
        func.count(PedidoOffline.factura_local_uuid)
    ).where(
        PedidoOffline.estado_sincronizacion != "ERROR",
        func.cast(PedidoOffline.fecha_creacion_local, Date) == date.today()
    )

    resultado = db.exec(statement).first()
    subtotal, impuestos, propina, total, conteo = resultado

    return {
        "subtotal": subtotal or 0,
        "total_impuestos": impuestos or 0,
        "propina_legal": propina or 0,
        "total_general": total or 0,
        "conteo_pedidos": conteo or 0,
        "origen": "CACHE_LOCAL",
        "mensaje": "CORE offline. Mostrando datos registrados localmente en la Capa de Integración. Pendiente de consolidación central."
    }


@router.get("/top-productos-vendidos")
async def get_top_productos_vendidos(db: Session = Depends(get_session)) -> Dict[str, Any]:
    reporte_core = await core_client.get("/reportes/top-productos-vendidos")

    if reporte_core:
        return {"origen": "CORE", "data": reporte_core}

    statement = select(
        Producto.nombre,
        func.sum(DetallePedidoOffline.cantidad).label("cantidad_vendida")
    ).join(
        Producto, DetallePedidoOffline.producto_id == Producto.id
    ).group_by(
        Producto.nombre
    ).order_by(
        desc("cantidad_vendida")
    ).limit(10)

    resultados = db.exec(statement).all()

    return {
        "origen": "CACHE_LOCAL",
        "mensaje": "CORE offline. Top basado únicamente en ventas locales no sincronizadas.",
        "data": [{"nombre": r[0], "cantidad_vendida": r[1]} for r in resultados]
    }


@router.get("/productos-stock-bajo")
async def get_productos_stock_bajo(db: Session = Depends(get_session)) -> Dict[str, Any]:
    reporte_core = await core_client.get("/reportes/productos-stock-bajo")

    if reporte_core:
        return {"origen": "CORE", "data": reporte_core}

    UMBRAL_CONTINGENCIA = 5

    statement = select(
        Producto.nombre,
        InventarioLocal.cantidad_disponible
    ).join(
        Producto, InventarioLocal.producto_id == Producto.id
    ).where(
        InventarioLocal.sucursal_id == settings.SUCURSAL_ID,
        InventarioLocal.cantidad_disponible <= UMBRAL_CONTINGENCIA
    )

    resultados = db.exec(statement).all()

    return {
        "origen": "CACHE_LOCAL",
        "mensaje": f"CORE offline. Stock bajo calculado con umbral fijo local de {UMBRAL_CONTINGENCIA} unidades.",
        "data": [
            {
                "nombre": r[0],
                "cantidad_disponible": r[1],
                "stock_minimo": UMBRAL_CONTINGENCIA
            } for r in resultados
        ]
    }