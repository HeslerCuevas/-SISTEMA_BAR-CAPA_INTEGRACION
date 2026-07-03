import uvicorn
import traceback
import asyncio
from app.services.scheduler import auto_sync_worker
import firebase_admin
from firebase_admin import credentials
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.loggin_middleware import AuditLoggingMiddleware
from app.db.database import engine
from sqlmodel import SQLModel, Session

from app.api.routers import (
    auth_empleados,
    productos,
    pedidos,
    empleados,
    inventario,
    auth_clientes,
    movil_mesas,
    promociones
)
from app.services.sync_service import procesar_pedidos_pendientes, procesar_movimientos_pendientes

security_scheme = HTTPBearer()

scheduler = AsyncIOScheduler()


async def tarea_sincronizacion_programada():
    print("[SCHEDULER] Despertando: Revisando bandejas de salida offline...")
    try:
        with Session(engine) as session:
            pedidos_ok, pedidos_fail = await procesar_pedidos_pendientes(session)
            mov_ok, mov_fail = await procesar_movimientos_pendientes(session)

            if pedidos_ok > 0 or pedidos_fail > 0 or mov_ok > 0 or mov_fail > 0:
                print(f"[SCHEDULER] Reporte de Sincronización:")
                print(f"  -> Pedidos: {pedidos_ok} subidos, {pedidos_fail} fallidos.")
                print(f"  -> Movimientos: {mov_ok} subidos, {mov_fail} fallidos.")
    except Exception as e:
        print(f"[ERROR SCHEDULER] Fallo durante la sincronización: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Iniciando Gateway...")

    asyncio.create_task(auto_sync_worker())
    print("Worker de auto-sincronización iniciado.")
    try:
        ruta_cert = Path("firebase-adminsdk.json")
        if ruta_cert.exists():
            cred = credentials.Certificate(str(ruta_cert))
            firebase_admin.initialize_app(cred)
            print("Firebase Admin SDK inicializado correctamente.")
        else:
            print("ADVERTENCIA: No se encontró 'firebase-adminsdk.json'. Las notificaciones Push no funcionarán.")
    except Exception as e:
        print(f"Error al inicializar Firebase: {e}")

    print("Verificando/Creando esquemas en SQL Server Local...")
    SQLModel.metadata.create_all(engine)

    print("Iniciando programador de tareas (Background Scheduler)...")
    scheduler.add_job(tarea_sincronizacion_programada, 'interval', seconds=10)
    scheduler.start()

    print("Sistema listo y protegido.")

    yield

    print("Apagando Gateway y deteniendo Scheduler...")
    scheduler.shutdown()


app = FastAPI(
    title="BAR INTEGRATION GATEWAY",
    description="Capa de Resiliencia, Seguridad y Auditoría para el Bar",
    version="1.0.0",
    swagger_ui_parameters={"persistAuthorization": True},
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(AuditLoggingMiddleware)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    print(f"[ERROR GLOBAL CRITICO] Fallo en la ruta {request.url.path}")
    traceback.print_exc()

    return JSONResponse(
        status_code=500,
        content={
            "status": "error",
            "mensaje": "El Gateway experimentó un fallo interno inesperado.",
            "detalle": str(exc)
        }
    )


app.include_router(auth_empleados.router, prefix="/api/v1")
app.include_router(auth_clientes.router, prefix="/api/v1")
app.include_router(productos.router, prefix="/api/v1")
app.include_router(pedidos.router, prefix="/api/v1")
app.include_router(empleados.router, prefix="/api/v1")
app.include_router(inventario.router, prefix="/api/v1")
app.include_router(movil_mesas.router, prefix="/api/v1")
app.include_router(promociones.router, prefix="/api/v1")


@app.get("/login-token-check", include_in_schema=False)
async def check_security():
    return {"status": "ok"}


@app.get("/", tags=["Estado del Sistema"])
async def root():
    return {
        "status": "Gateway Online",
        "mode": "Resilient",
        "scheduler": "Activo"
    }


if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8001, reload=True)