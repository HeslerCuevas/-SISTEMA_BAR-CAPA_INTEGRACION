from typing import List, Optional
from pydantic import BaseModel

class DetallePedidoRequest(BaseModel):
    producto_id: int
    cantidad: int
    precio_unitario: float
    monto_impuesto: float
    subtotal_linea: float

class PedidoRequest(BaseModel):
    mesa: Optional[int] = None
    subtotal: float
    total_impuestos: float
    propina_legal: float = 0.0
    total_general: float
    detalles: List[DetallePedidoRequest]

class PedidoResponse(BaseModel):
    mensaje: str
    factura_local_uuid: str
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
    nuevo_subtotal_agregado: float
    nuevo_impuesto_agregado: float
    detalles_adicionales: List[DetalleItemAdicional]

class SolicitarCuentaRequest(BaseModel):
    metodo_pago_preferido: str = "EFECTIVO" # o TARJETA
    propina_voluntaria_extra: float = 0.0

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
    total_general_acumulado: float
    items_consumidos: List[ItemResumen]