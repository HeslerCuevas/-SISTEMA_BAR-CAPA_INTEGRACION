from sqlmodel import Session, select
from app.db.database import engine
from app.models.integration_models import Producto, Categoria, Impuesto


def seed_productos():
    print("Conectando a la base de datos para sembrar productos...")
    with Session(engine) as session:
        # 1. Asegurar Categoría Comodín
        categoria = session.get(Categoria, 1)
        if not categoria:
            categoria = Categoria(id=1, nombre="General", descripcion="Categoría de prueba")
            session.add(categoria)
            print("⏳ Categoría 'General' creada.")

        # 2. Asegurar Impuesto Comodín
        impuesto = session.get(Impuesto, 1)
        if not impuesto:
            impuesto = Impuesto(id=1, nombre="ITBIS", tasa_porcentaje=18.0)
            session.add(impuesto)
            print("⏳ Impuesto 'ITBIS' creado.")

        session.commit()  # Guardar padres para evitar errores de FK

        # 3. Crear Productos con TODOS los campos obligatorios
        p1 = Producto(
            id=1,
            sku="CERV-PRES-01",  # <--- No puede ser NULL
            nombre="Cerveza Presidente",
            precio_base=250.00,
            categoria_id=1,
            impuesto_id=1,
            es_inventariable=True,  # <--- Agregado por seguridad
            activo=True
        )

        p2 = Producto(
            id=2,
            sku="PICA-POLLO-01",  # <--- No puede ser NULL
            nombre="Servicio de Pica Pollo",
            precio_base=450.00,
            categoria_id=1,
            impuesto_id=1,
            es_inventariable=True,
            activo=True
        )

        # Merge actualiza si existe o inserta si es nuevo
        session.merge(p1)
        session.merge(p2)
        session.commit()

        print("✅ PRODUCTOS DE PRUEBA LISTOS EN CACHÉ LOCAL.")


if __name__ == "__main__":
    seed_productos()