from pydantic import BaseModel
from typing import Optional
import uuid

class MesaVincularRequest(BaseModel):
    codigo_qr_mesa: str
    numero_mesa: int

class MesaVincularResponse(BaseModel):
    mensaje: str
    estado_mesa: str
    numero_mesa: int
    factura_local_uuid_activa: Optional[uuid.UUID] = None

class LlamarMeseroRequest(BaseModel):
    motivo_llamada: str = "ASISTENCIA_GENERAL"

class LlamarMeseroResponse(BaseModel):
    mensaje: str