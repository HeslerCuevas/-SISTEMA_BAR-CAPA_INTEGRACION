from pydantic import BaseModel
from decimal import Decimal

class DetallePedidoRequest(BaseModel):
    producto_id: int
    cantidad: int
    precio_unitario: float
    monto_impuesto: float
    subtotal_linea: float
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

class PedidoResponse(BaseModel):
    mensaje: str
    factura_local_uuid: str
    propina_extra: float
    estado_sincronizacion: str

from pydantic import BaseModel
from typing import List, Optional
import uuid

class DetalleItemAdicional(BaseModel):
    detalle_local_uuid: uuid.UUID
    producto_id: int
    cantidad: int
    precio_unitario: float
    monto_impuesto: float
    subtotal_linea: float

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
    subtotal_linea: float
    estado_preparacion: str

class ResumenCuentaResponse(BaseModel):
    factura_local_uuid: uuid.UUID
    estado_cuenta: str
    subtotal_acumulado: float
    total_impuestos_acumulado: float
    propina_legal_acumulada: float
    propina_extra_acumulada: float
    total_general_acumulado: float
    items_consumidos: List[ItemResumen]
