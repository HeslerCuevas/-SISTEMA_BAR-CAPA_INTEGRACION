from pydantic import BaseModel
from typing import Optional

class ProductoResponse(BaseModel):
    id: int
    nombre: str
    precio_base: float
    cantidad_disponible: int
    origen_datos: str
    imagen_url: Optional[str] = None

class CategoriaBase(BaseModel):
    nombre: str
    descripcion: Optional[str] = None
    activo: bool = True

class CategoriaCreate(CategoriaBase):
    pass

class CategoriaResponse(CategoriaBase):
    id: int

    class Config:
        from_attributes = True  # Esto permite a Pydantic leer desde modelos de SQLAlchemy/SQLModel