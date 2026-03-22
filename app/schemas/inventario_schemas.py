from pydantic import BaseModel
import uuid
from typing import Literal
from datetime import datetime
from sqlmodel import SQLModel, Field, Column, String, Integer, DateTime, text


class MovimientoCreate(BaseModel):
    tipo_movimiento: Literal["ENTRADA", "SALIDA", "AJUSTE"] = Field(..., description="Tipo de movimiento")
    producto_id: int = Field(..., gt=0, description="ID del producto")
    cantidad: int = Field(..., gt=0, description="Cantidad (entero)")
    motivo: str = Field(..., description="Motivo obligatorio del movimiento")


class MovimientoOffline(SQLModel, table=True):
    __tablename__ = "Movimientos_Offline"
    __table_args__ = {"schema": "Sync"}

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    empleado_id: int = Field(sa_column=Column("EmpleadoId", Integer, nullable=False))
    tipo_movimiento: str = Field(sa_column=Column("TipoMovimiento", String(20), nullable=False))
    producto_id: int = Field(sa_column=Column("ProductoId", Integer, nullable=False))
    cantidad: int = Field(sa_column=Column("Cantidad", Integer, nullable=False))
    motivo: str = Field(sa_column=Column("Motivo", String(255), nullable=False))
    estado_sync: str = Field(sa_column=Column("EstadoSync", String(20), server_default=text("'PENDIENTE'")))
    fecha_creacion: datetime = Field(default_factory=datetime.utcnow, sa_column=Column("FechaCreacion", DateTime))