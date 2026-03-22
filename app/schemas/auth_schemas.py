from pydantic import BaseModel
class LoginRequest(BaseModel):
    identificador: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    canal: str
    usuario_id: int


class ProductoResponse(BaseModel):
    id: int
    nombre: str
    precio_base: float
    cantidad_disponible: int
    origen_datos: str