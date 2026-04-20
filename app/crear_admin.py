from sqlmodel import Session
from app.db.database import engine
from app.models.integration_models import Empleado, Rol, Sucursal
from app.core.security import get_password_hash


def fix_admin():
    print("Iniciando actualización segura del administrador...")
    with Session(engine) as session:
        if not session.get(Rol, 1):
            session.add(Rol(id=1, nombre="Admin"))
        if not session.get(Sucursal, 1):
            session.add(Sucursal(id=1, nombre="Sucursal Central", activo=True))
        session.commit()

        admin = session.get(Empleado, 1)

        if admin:
            print(f"Actualizando datos del admin existente (ID: 1)...")
            admin.documento_identidad = "admin"
            admin.nombre_completo = "Administrador de Sistema"
            admin.gmail = "admin@bar.com"
            admin.password_hash = get_password_hash("secreto123")
            admin.activo = True
        else:
            print(f"Creando nuevo administrador (ID: 1)...")
            admin = Empleado(
                id=1,
                rol_id=1,
                sucursal_id=1,
                documento_identidad="admin",
                nombre_completo="Administrador de Sistema",
                gmail="admin@bar.com",
                password_hash=get_password_hash("secreto123"),
                activo=True
            )
            session.add(admin)

        try:
            session.commit()
            print("¡Administrador actualizado y listo para loguear!")
        except Exception as e:
            session.rollback()
            print(f"Error fatal: {e}")


if __name__ == "__main__":
    fix_admin()