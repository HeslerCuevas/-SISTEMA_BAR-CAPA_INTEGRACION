from typing import Optional, List
from decimal import Decimal
from datetime import datetime
import uuid

from sqlmodel import SQLModel, Field, Relationship
from sqlalchemy import Column, String, Integer, BigInteger, DateTime, Numeric, Boolean, ForeignKey, text, SmallInteger
from sqlalchemy.dialects.mssql import UNIQUEIDENTIFIER


class TransaccionAPI(SQLModel, table=True):
    __tablename__ = "Transacciones_API"
    __table_args__ = {"schema": "Audit"}

    id: Optional[int] = Field(default=None, sa_column=Column("Id", BigInteger, primary_key=True, autoincrement=True))
    fecha_hora: datetime = Field(default_factory=datetime.now,
                                 sa_column=Column("FechaHora", DateTime, server_default=text("SYSDATETIME()"),
                                                  nullable=False))
    direccion: str = Field(sa_column=Column("Direccion", String(10), nullable=False))
    metodo_http: str = Field(sa_column=Column("MetodoHTTP", String(10), nullable=False))
    endpoint: str = Field(sa_column=Column("Endpoint", String(255), nullable=False))
    status_code: int = Field(sa_column=Column("StatusCode", Integer, nullable=False))
    tiempo_respuesta_ms: int = Field(sa_column=Column("TiempoRespuestaMs", Integer, nullable=False))
    ip_origen: Optional[str] = Field(default=None, sa_column=Column("IpOrigen", String(50)))
    payload_request: Optional[str] = Field(default=None, sa_column=Column("PayloadRequest", String))
    payload_response: Optional[str] = Field(default=None, sa_column=Column("PayloadResponse", String))


class Rol(SQLModel, table=True):
    __tablename__ = "Roles"
    __table_args__ = {"schema": "Cache"}

    # autoincrement=False porque el ID viene del CORE
    id: int = Field(sa_column=Column("Id", Integer, primary_key=True, autoincrement=False))
    nombre: str = Field(sa_column=Column("Nombre", String(50), nullable=False))

    empleados: List["Empleado"] = Relationship(back_populates="rol")


class Sucursal(SQLModel, table=True):
    __tablename__ = "Sucursales"
    __table_args__ = {"schema": "Cache"}

    id: int = Field(sa_column=Column("Id", Integer, primary_key=True, autoincrement=False))
    nombre: str = Field(sa_column=Column("Nombre", String(100), nullable=False))

    empleados: List["Empleado"] = Relationship(back_populates="sucursal")
    inventarios: List["InventarioLocal"] = Relationship(back_populates="sucursal")


class Empleado(SQLModel, table=True):
    __tablename__ = "Empleados"
    __table_args__ = {"schema": "Cache"}

    id: int = Field(sa_column=Column("Id", Integer, primary_key=True, autoincrement=False))
    rol_id: int = Field(sa_column=Column("RolId", Integer, ForeignKey("Cache.Roles.Id"), nullable=False))
    sucursal_id: int = Field(sa_column=Column("SucursalId", Integer, ForeignKey("Cache.Sucursales.Id"), nullable=False))
    documento_identidad: str = Field(sa_column=Column("DocumentoIdentidad", String(20), nullable=False))
    nombre_completo: str = Field(sa_column=Column("NombreCompleto", String(150), nullable=False))
    password_hash: str = Field(sa_column=Column("PasswordHash", String(255), nullable=False))
    activo: bool = Field(default=True, sa_column=Column("Activo", Boolean, server_default=text("1"), nullable=False))

    rol: Rol = Relationship(back_populates="empleados")
    sucursal: Sucursal = Relationship(back_populates="empleados")
    pedidos_offline: List["PedidoOffline"] = Relationship(back_populates="empleado")


class Cliente(SQLModel, table=True):
    __tablename__ = "Clientes"
    __table_args__ = {"schema": "Cache"}

    id: int = Field(sa_column=Column("Id", Integer, primary_key=True, autoincrement=False))
    nombre_completo: str = Field(sa_column=Column("NombreCompleto", String(150), nullable=False))
    email: str = Field(sa_column=Column("Email", String(150), nullable=False))
    password_hash: str = Field(sa_column=Column("PasswordHash", String(255), nullable=False))
    puntos_lealtad: int = Field(default=0,
                                sa_column=Column("PuntosLealtad", Integer, server_default=text("0"), nullable=False))

    dispositivos: List["DispositivoCliente"] = Relationship(back_populates="cliente")
    pedidos_offline: List["PedidoOffline"] = Relationship(back_populates="cliente")


class DispositivoCliente(SQLModel, table=True):
    __tablename__ = "Dispositivos_Clientes"
    __table_args__ = {"schema": "Cache"}

    # Este sí es autoincremental, porque se genera en el Gateway
    id: Optional[int] = Field(default=None, sa_column=Column("Id", Integer, primary_key=True, autoincrement=True))
    cliente_id: int = Field(sa_column=Column("ClienteId", Integer, ForeignKey("Cache.Clientes.Id"), nullable=False))
    fcm_token: str = Field(sa_column=Column("FcmToken", String(1000), nullable=False))
    plataforma: str = Field(sa_column=Column("Plataforma", String(20), nullable=False))
    ultima_conexion: datetime = Field(default_factory=datetime.now,
                                      sa_column=Column("UltimaConexion", DateTime, server_default=text("SYSDATETIME()"),
                                                       nullable=False))

    cliente: Cliente = Relationship(back_populates="dispositivos")


class Impuesto(SQLModel, table=True):
    __tablename__ = "Impuestos"
    __table_args__ = {"schema": "Cache"}

    id: int = Field(sa_column=Column("Id", Integer, primary_key=True, autoincrement=False))
    nombre: str = Field(sa_column=Column("Nombre", String(50), nullable=False))
    tasa_porcentaje: Decimal = Field(sa_column=Column("TasaPorcentaje", Numeric(5, 2), nullable=False))

    productos: List["Producto"] = Relationship(back_populates="impuesto")


class Categoria(SQLModel, table=True):
    __tablename__ = "Categorias"
    __table_args__ = {"schema": "Cache"}

    id: int = Field(sa_column=Column("Id", Integer, primary_key=True, autoincrement=False))
    nombre: str = Field(sa_column=Column("Nombre", String(100), nullable=False))

    productos: List["Producto"] = Relationship(back_populates="categoria")


class Producto(SQLModel, table=True):
    __tablename__ = "Productos"
    __table_args__ = {"schema": "Cache"}

    id: int = Field(sa_column=Column("Id", Integer, primary_key=True, autoincrement=False))
    categoria_id: int = Field(
        sa_column=Column("CategoriaId", Integer, ForeignKey("Cache.Categorias.Id"), nullable=False))
    impuesto_id: int = Field(sa_column=Column("ImpuestoId", Integer, ForeignKey("Cache.Impuestos.Id"), nullable=False))
    sku: str = Field(sa_column=Column("SKU", String(50), nullable=False))
    nombre: str = Field(sa_column=Column("Nombre", String(150), nullable=False))
    precio_base: Decimal = Field(sa_column=Column("PrecioBase", Numeric(12, 2), nullable=False))
    es_inventariable: bool = Field(default=True, sa_column=Column("EsInventariable", Boolean, server_default=text("1"),
                                                                  nullable=False))
    activo: bool = Field(default=True, sa_column=Column("Activo", Boolean, server_default=text("1"), nullable=False))

    categoria: Categoria = Relationship(back_populates="productos")
    impuesto: Impuesto = Relationship(back_populates="productos")
    inventarios: List["InventarioLocal"] = Relationship(back_populates="producto")
    detalles_pedido: List["DetallePedidoOffline"] = Relationship(back_populates="producto")


class InventarioLocal(SQLModel, table=True):
    __tablename__ = "Inventario_Local"
    __table_args__ = {"schema": "Cache"}

    # Llave primaria compuesta
    producto_id: int = Field(
        sa_column=Column("ProductoId", Integer, ForeignKey("Cache.Productos.Id"), primary_key=True))
    sucursal_id: int = Field(
        sa_column=Column("SucursalId", Integer, ForeignKey("Cache.Sucursales.Id"), primary_key=True))

    cantidad_disponible: int = Field(sa_column=Column("CantidadDisponible", Integer, nullable=False))
    ultima_sincronizacion: datetime = Field(default_factory=datetime.now,
                                            sa_column=Column("UltimaSincronizacion", DateTime,
                                                             server_default=text("SYSDATETIME()"), nullable=False))

    producto: Producto = Relationship(back_populates="inventarios")
    sucursal: Sucursal = Relationship(back_populates="inventarios")


class PedidoOffline(SQLModel, table=True):
    __tablename__ = "Pedidos_Offline"
    __table_args__ = {"schema": "Sync"}

    factura_local_uuid: uuid.UUID = Field(default_factory=uuid.uuid4,
                                          sa_column=Column("Factura_Local_UUID", UNIQUEIDENTIFIER, primary_key=True))
    empleado_id: Optional[int] = Field(default=None,
                                       sa_column=Column("EmpleadoId", Integer, ForeignKey("Cache.Empleados.Id")))
    cliente_id: Optional[int] = Field(default=None,
                                      sa_column=Column("ClienteId", Integer, ForeignKey("Cache.Clientes.Id")))
    canal_origen: str = Field(sa_column=Column("CanalOrigen", String(50), nullable=False))
    mesa: Optional[int] = Field(default=None, sa_column=Column("Mesa", SmallInteger))
    subtotal: Decimal = Field(sa_column=Column("Subtotal", Numeric(12, 2), nullable=False))
    total_impuestos: Decimal = Field(sa_column=Column("TotalImpuestos", Numeric(12, 2), nullable=False))
    propina_legal: Decimal = Field(default=Decimal("0.0"),
                                   sa_column=Column("PropinaLegal", Numeric(12, 2), server_default=text("0"),
                                                    nullable=False))
    total_general: Decimal = Field(sa_column=Column("TotalGeneral", Numeric(12, 2), nullable=False))
    fecha_creacion_local: datetime = Field(default_factory=datetime.now,
                                           sa_column=Column("FechaCreacionLocal", DateTime,
                                                            server_default=text("SYSDATETIME()"), nullable=False))
    estado_sincronizacion: str = Field(default="PENDIENTE", sa_column=Column("EstadoSincronizacion", String(20),
                                                                             server_default=text("'PENDIENTE'"),
                                                                             nullable=False))
    intentos_sincronizacion: int = Field(default=0,
                                         sa_column=Column("IntentosSincronizacion", Integer, server_default=text("0"),
                                                          nullable=False))
    ultimo_error: Optional[str] = Field(default=None, sa_column=Column("UltimoError", String))

    empleado: Optional[Empleado] = Relationship(back_populates="pedidos_offline")
    cliente: Optional[Cliente] = Relationship(back_populates="pedidos_offline")
    detalles: List["DetallePedidoOffline"] = Relationship(back_populates="pedido")


class DetallePedidoOffline(SQLModel, table=True):
    __tablename__ = "Detalles_Pedido_Offline"
    __table_args__ = {"schema": "Sync"}

    detalle_local_uuid: uuid.UUID = Field(default_factory=uuid.uuid4,
                                          sa_column=Column("Detalle_Local_UUID", UNIQUEIDENTIFIER, primary_key=True))
    factura_local_uuid: uuid.UUID = Field(
        sa_column=Column("Factura_Local_UUID", UNIQUEIDENTIFIER, ForeignKey("Sync.Pedidos_Offline.Factura_Local_UUID"),
                         nullable=False))
    producto_id: int = Field(sa_column=Column("ProductoId", Integer, ForeignKey("Cache.Productos.Id"), nullable=False))
    cantidad: int = Field(sa_column=Column("Cantidad", Integer, nullable=False))
    precio_unitario_historico: Decimal = Field(
        sa_column=Column("PrecioUnitarioHistorico", Numeric(12, 2), nullable=False))
    impuesto_historico: Decimal = Field(sa_column=Column("ImpuestoHistorico", Numeric(5, 2), nullable=False))
    monto_impuesto: Decimal = Field(sa_column=Column("MontoImpuesto", Numeric(12, 2), nullable=False))
    subtotal_linea: Decimal = Field(sa_column=Column("SubtotalLinea", Numeric(12, 2), nullable=False))

    pedido: PedidoOffline = Relationship(back_populates="detalles")
    producto: Producto = Relationship(back_populates="detalles_pedido")