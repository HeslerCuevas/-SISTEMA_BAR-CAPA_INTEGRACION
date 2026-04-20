import logging
from sqlmodel import Session, select
from app.clients.core_client import core_client
from app.models.integration_models import Rol, Sucursal, Empleado, Producto, Categoria, Impuesto

logger = logging.getLogger("CacheService")


async def sincronizar_productos_desde_core(db: Session):
    try:
        impuestos_core = await core_client.get("/productos/impuestos")
        if impuestos_core:
            for i in impuestos_core:
                stmt = select(Impuesto).where(Impuesto.id == i['id'])
                imp_local = db.exec(stmt).first()
                if not imp_local:
                    db.add(Impuesto(id=i['id'], nombre=i['nombre'], tasa_porcentaje=i['tasa_porcentaje']))
                else:
                    imp_local.nombre = i['nombre']
                    imp_local.tasa_porcentaje = i['tasa_porcentaje']
            db.commit()
            logger.info("Caché de Impuestos actualizada.")

        categorias_core = await core_client.get("/productos/categorias")
        if categorias_core:
            for c in categorias_core:
                stmt = select(Categoria).where(Categoria.id == c['id'])
                cat_local = db.exec(stmt).first()
                if not cat_local:
                    db.add(Categoria(id=c['id'], nombre=c['nombre']))
                else:
                    cat_local.nombre = c['nombre']
            db.commit()
            logger.info("Caché de Categorías actualizada.")

        productos_core = await core_client.get("/productos/")
        if productos_core:
            contador_p = 0
            for p in productos_core:
                stmt = select(Producto).where(Producto.id == p['id'])
                prod_local = db.exec(stmt).first()

                if not prod_local:
                    nuevo_p = Producto(
                        id=p['id'],
                        categoria_id=p['categoria_id'],
                        impuesto_id=p['impuesto_id'],
                        sku=p['sku'],
                        nombre=p['nombre'],
                        precio_base=p['precio_base'],
                        es_inventariable=p.get('es_inventariable', True),
                        activo=p.get('activo', True),
                        imagen_url=p.get('imagen_url')
                    )
                    db.add(nuevo_p)
                else:
                    prod_local.nombre = p['nombre']
                    prod_local.precio_base = p['precio_base']
                    prod_local.imagen_url = p.get('imagen_url')
                    prod_local.activo = p.get('activo', True)

                contador_p += 1

            db.commit()
            logger.info(f"Sincronización de {contador_p} productos completada exitosamente.")
            return {"status": "success", "total": contador_p}

        return {"status": "warning", "mensaje": "No se recibieron productos del CORE."}

    except Exception as e:
        db.rollback()
        logger.error(f"Error en la cascada de sincronización: {str(e)}")
        return {"status": "error", "mensaje": str(e)}

async def sincronizar_catalogos_base(db: Session):
    try:
        roles_core = await core_client.get("/roles/")
        if roles_core:
            for r in roles_core:
                stmt = select(Rol).where(Rol.id == r['id'])
                existe = db.exec(stmt).first()
                if not existe:
                    nuevo_rol = Rol(id=r['id'], nombre=r['nombre'])
                    db.add(nuevo_rol)
            db.commit()

        suc_core = await core_client.get("/sucursales/")
        if suc_core:
            for s in suc_core:
                stmt = select(Sucursal).where(Sucursal.id == s['id'])
                existe = db.exec(stmt).first()
                if not existe:
                    nueva_suc = Sucursal(id=s['id'], nombre=s['nombre'])
                    db.add(nueva_suc)
            db.commit()

        return True
    except Exception as e:
        db.rollback()
        logger.error(f"Error sincronizando catálogos base: {e}")
        return False



async def sincronizar_personal_desde_core(db: Session):
    try:
        await sincronizar_catalogos_base(db)
        empleados_core = await core_client.get("/empleados/")

        if empleados_core is None:
            return {"status": "error", "mensaje": "CORE apagado o inalcanzable."}

        contador_nuevos = 0
        contador_actualizados = 0

        for emp_data in empleados_core:
            statement = select(Empleado).where(Empleado.id == emp_data["id"])
            empleado_local = db.exec(statement).first()

            if empleado_local:
                empleado_local.nombre_completo = emp_data["nombre_completo"]
                empleado_local.rol_id = emp_data["rol_id"]
                empleado_local.sucursal_id = emp_data["sucursal_id"]
                empleado_local.password_hash = emp_data["password_hash"]
                empleado_local.activo = emp_data["activo"]
                empleado_local.gmail = emp_data.get("email")
                contador_actualizados += 1
            else:
                nuevo_empleado = Empleado(
                    id=emp_data["id"],
                    rol_id=emp_data["rol_id"],
                    sucursal_id=emp_data["sucursal_id"],
                    documento_identidad=emp_data["documento_identidad"],
                    nombre_completo=emp_data["nombre_completo"],
                    password_hash=emp_data["password_hash"],
                    activo=emp_data.get("activo", True),
                    gmail=emp_data.get("email")
                )
                db.add(nuevo_empleado)
                contador_nuevos += 1

        db.commit()
        return {
            "status": "success",
            "mensaje": f"Sincronizados: {contador_nuevos} nuevos, {contador_actualizados} actualizados."
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Fallo en sync de empleados: {str(e)}")
        return {"status": "error", "mensaje": f"Error interno: {str(e)}"}