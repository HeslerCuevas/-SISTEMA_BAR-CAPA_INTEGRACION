import pytest
from fastapi.testclient import TestClient
from app.models.integration_models import Producto, Categoria, Impuesto

def test_get_categorias_local(client: TestClient, db_session):
    cat = Categoria(id=99, nombre="Categoria Local")
    db_session.add(cat)
    db_session.commit()

    response = client.get("/api/v1/productos/categorias")
    assert response.status_code == 200
    assert isinstance(response.json(), list)

def test_get_productos_por_categoria(client: TestClient, db_session):
    cat = Categoria(id=100, nombre="Cat 2")
    imp = Impuesto(id=100, nombre="Imp 2", tasa_porcentaje=18.0)
    db_session.add_all([cat, imp])
    db_session.commit()

    prod = Producto(id=100, categoria_id=100, impuesto_id=100, sku="SKULOCAL", nombre="Prod Local", precio_base=10.0)
    db_session.add(prod)
    db_session.commit()

    response = client.get("/api/v1/productos/por-categoria/100")
    assert response.status_code == 200
    assert isinstance(response.json(), list)

def test_get_todos_productos_local(client: TestClient):
    response = client.get("/api/v1/productos/")
    assert response.status_code == 200
    assert isinstance(response.json(), list)

def test_get_producto_por_id_local(client: TestClient, db_session):
    cat = Categoria(id=101, nombre="Cat 3")
    imp = Impuesto(id=101, nombre="Imp 3", tasa_porcentaje=18.0)
    db_session.add_all([cat, imp])
    db_session.commit()

    prod = Producto(id=101, categoria_id=101, impuesto_id=101, sku="SKU3", nombre="Prod 3", precio_base=20.0)
    db_session.add(prod)
    db_session.commit()

    response = client.get("/api/v1/productos/101")
    assert response.status_code == 200
    assert response.json()["nombre"] == "Prod 3"

def test_get_producto_inexistente(client: TestClient):
    response = client.get("/api/v1/productos/999999")
    assert response.status_code == 404
