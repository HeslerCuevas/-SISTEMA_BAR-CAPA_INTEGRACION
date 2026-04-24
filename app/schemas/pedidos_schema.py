from pydantic import BaseModel, Field
from decimal import Decimal
from typing import List, Optional, Literal
from datetime import datetime
import uuid

class DetallePedidoCreate(BaseModel):
    producto_id: int
    cantidad: int = Field(..., gt=0, description="La cantidad debe ser mayor a cero")
    detalle_local_uuid: Optional[uuid.UUID] = None

class PedidoCreate(BaseModel):
    empleado_id: Optional[int] = None
    cliente_id: Optional[int] = None
    canal_origen: Literal["CAJA", "MOVIL", "WEB"]
    mesa: Optional[int] = None
    propina_extra: Decimal = Decimal("0.0")
    factura_local_uuid: Optional[uuid.UUID] = None
    detalles: List[DetallePedidoCreate]

class DetallePedidoRequest(BaseModel):
    producto_id: int
    cantidad: int
    precio_unitario: Decimal
    monto_impuesto: Decimal
    subtotal_linea: Decimal
    detalle_local_uuid: Optional[uuid.UUID] = None

class PedidoRequest(BaseModel):
    factura_local_uuid: Optional[uuid.UUID] = None
    mesa: Optional[int] = None
    subtotal: Decimal
    total_impuestos: Decimal
    propina_legal: Decimal = Decimal("0.0")
    propina_extra: Decimal = Decimal("0.0")
    total_general: Decimal
    detalles: List[DetallePedidoRequest]

class DetallePedidoResponse(BaseModel):
    id: int
    producto_id: int
    cantidad: int
    precio_unitario_historico: Decimal
    impuesto_historico: Decimal
    monto_impuesto: Decimal
    subtotal_linea: Decimal
    detalle_local_uuid: Optional[uuid.UUID]

    class Config:
        from_attributes = True

class PedidoResponse(BaseModel):
    mensaje: Optional[str] = None
    id: Optional[int] = None
    factura_local_uuid: Optional[str] = None
    cliente_id: Optional[int] = None
    canal_origen: Optional[str] = None
    mesa: Optional[int] = None
    estado: Optional[str] = None
    estado_sincronizacion: Optional[str] = None
    propina_legal: Optional[Decimal] = None
    subtotal: Optional[Decimal] = None
    total_impuestos: Optional[Decimal] = None
    propina_extra: Optional[Decimal] = None
    total_general: Optional[Decimal] = None
    fecha_creacion: Optional[datetime] = None

    class Config:
        from_attributes = True

class CancelarPedidoRequest(BaseModel):
    empleado_id: int
    motivo: str

class DetalleItemAdicional(BaseModel):
    detalle_local_uuid: uuid.UUID
    producto_id: int
    cantidad: int
    precio_unitario: Decimal
    monto_impuesto: Decimal
    subtotal_linea: Decimal

class AgregarItemsRequest(BaseModel):
    cliente_id: Optional[int] = None
    nuevo_subtotal_agregado: Decimal
    nuevo_impuesto_agregado: Decimal
    detalles_adicionales: List[DetalleItemAdicional]

class SolicitarCuentaRequest(BaseModel):
    metodo_pago_preferido: str = "EFECTIVO"
    propina_extra: Decimal = Decimal("0.0")

class ItemResumen(BaseModel):
    producto_nombre: str
    cantidad: int
    subtotal_linea: Decimal
    estado_preparacion: str

class ResumenCuentaResponse(BaseModel):
    factura_local_uuid: uuid.UUID
    estado_cuenta: str
    subtotal_acumulado: Decimal
    total_impuestos_acumulado: Decimal
    propina_legal_acumulada: Decimal
    propina_extra_acumulada: Decimal
    total_general_acumulado: Decimal
    items_consumidos: List[ItemResumen]