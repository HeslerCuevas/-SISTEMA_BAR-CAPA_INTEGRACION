import os
import logging
from sqlmodel import Session
from typing import Dict, Any

from app.models.integration_models import Empleado, Rol, Sucursal
from app.clients.core_client import core_client

logger = logging.getLogger("CacheService")


async def sincronizar_personal_desde_core(db: Session) -> Dict[str, Any]:
    logger.info("Iniciando sincronización de Personal desde el CORE...")

    mi_sucursal_id = int(os.getenv("SUCURSAL_ID", 1))

    parametros = {
        "sucursal_id": mi_sucursal_id
    }

    datos_core = await core_client.get("/sync/seguridad/usuarios", params=parametros)

    if datos_core is None:
        logger.warning("CORE inaccesible o rechazó la petición. No se pudo actualizar la caché de personal.")
        return {"status": "error", "mensaje": "El CORE no respondió o la petición falló. La caché sigue intacta."}

    try:
        stats = {"empleados_actualizados": 0, "roles_creados": 0, "sucursales_creadas": 0}

        lista_empleados = datos_core if isinstance(datos_core, list) else datos_core.get("empleados", [])

        for emp_data in lista_empleados:

            rol = db.get(Rol, emp_data["rol_id"])
            if not rol:
                nuevo_rol = Rol(id=emp_data["rol_id"], nombre=f"Rol Importado {emp_data['rol_id']}")
                db.add(nuevo_rol)
                stats["roles_creados"] += 1

            sucursal = db.get(Sucursal, emp_data["sucursal_id"])
            if not sucursal:
                nueva_sucursal = Sucursal(id=emp_data["sucursal_id"], nombre=f"Sucursal {emp_data['sucursal_id']}",
                                          activo=True)
                db.add(nueva_sucursal)
                stats["sucursales_creadas"] += 1

            db.commit()

            empleado = db.get(Empleado, emp_data["id"])

            if not empleado:
                empleado = Empleado(
                    id=emp_data["id"],
                    rol_id=emp_data["rol_id"],
                    sucursal_id=emp_data["sucursal_id"],
                    documento_identidad=emp_data["documento_identidad"],
                    nombre_completo=emp_data["nombre_completo"],
                    email=emp_data.get("email", "sin_email@bar.com"),
                    password_hash=emp_data["password_hash"],
                    activo=emp_data["activo"]
                )
                db.add(empleado)
            else:
                empleado.rol_id = emp_data["rol_id"]
                empleado.sucursal_id = emp_data["sucursal_id"]
                empleado.documento_identidad = emp_data["documento_identidad"]
                empleado.nombre_completo = emp_data["nombre_completo"]
                empleado.password_hash = emp_data["password_hash"]
                empleado.activo = emp_data["activo"]
                empleado.gmail = emp_data.get("email")

            stats["empleados_actualizados"] += 1

        db.commit()
        logger.info(f"Sincronización exitosa: {stats}")

        return {"status": "success", "mensaje": "Caché de personal actualizada correctamente", "stats": stats}

    except Exception as e:
        db.rollback()
        logger.error(f"Error procesando los datos del CORE: {e}")
        return {"status": "error", "mensaje": f"Error interno al guardar en caché local: {str(e)}"}