from pydantic import BaseModel
from typing import Optional
class LoginRequest(BaseModel):
    identificador: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    canal: str
    usuario_id: int


class ClienteRegistroRequest(BaseModel):
    nombre_completo: str
    email: str
    telefono: Optional[str] = None
    password_plano: str

class ClienteRegistroResponse(BaseModel):
    mensaje: str
    cliente_id: int
    email: str

class ClienteLoginRequest(BaseModel):
    email: str
    password_plano: str

class ClienteLoginResponse(BaseModel):
    access_token: str
    token_type: str
    canal: str
    cliente_id: int
    nombre_completo: str