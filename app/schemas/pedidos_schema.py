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