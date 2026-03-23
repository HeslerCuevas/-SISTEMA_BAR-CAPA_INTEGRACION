from pydantic import BaseModel
from typing import Literal, Optional
from sqlmodel import Field


class MovimientoCreate(BaseModel):
    tipo_movimiento: Literal["ENTRADA", "SALIDA", "AJUSTE"] = Field(..., description="Tipo de movimiento")
    producto_id: int = Field(..., gt=0, description="ID del producto")
    cantidad: int = Field(..., gt=0, description="Cantidad (entero)")
    motivo: str = Field(..., description="Motivo obligatorio del movimiento")
    movimiento_local_uuid: Optional[str] = Field(None, description="UUID generado por el Gateway")