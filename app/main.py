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
    pedidos_movil,
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
    print("[SCHEDULER] Waking up: Checking offline outboxes...")
    try:
        with Session(engine) as session:
            pedidos_ok, pedidos_fail = await procesar_pedidos_pendientes(session)
            mov_ok, mov_fail = await procesar_movimientos_pendientes(session)

            if pedidos_ok > 0 or pedidos_fail > 0 or mov_ok > 0 or mov_fail > 0:
                print(f"[SCHEDULER] Synchronization report:")
                print(f"  -> Orders: {pedidos_ok} uploaded, {pedidos_fail} failed.")
                print(f"  -> Movements: {mov_ok} uploaded, {mov_fail} failed.")
    except Exception as e:
        print(f"[SCHEDULER ERROR] Synchronization failed: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Starting Gateway...")

    asyncio.create_task(auto_sync_worker())
    print("Automatic synchronization worker started.")
    try:
        # Resolve this from the application package rather than from the
        # process working directory.  The Gateway can be started from the
        # repository root, a service manager, or an IDE, none of which put the
        # certificate in the current directory.
        ruta_cert = Path(__file__).resolve().parent / "firebase-adminsdk.json"
        if ruta_cert.exists():
            try:
                firebase_admin.get_app()
                print("Firebase Admin SDK is already initialized.")
            except ValueError:
                cred = credentials.Certificate(str(ruta_cert))
                firebase_admin.initialize_app(cred)
                print("Firebase Admin SDK initialized successfully.")
        else:
            print(f"WARNING: Firebase credential was not found at {ruta_cert}. Push notifications will not work.")
    except Exception as e:
        print(f"Error initializing Firebase: {e}")

    print("Checking/creating schemas in local SQL Server...")
    SQLModel.metadata.create_all(engine)

    print("Starting task scheduler (Background Scheduler)...")
    scheduler.add_job(tarea_sincronizacion_programada, 'interval', seconds=10)
    scheduler.start()

    print("System ready and protected.")

    yield

    print("Shutting down Gateway and stopping Scheduler...")
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
    print(f"[CRITICAL GLOBAL ERROR] Request failed at {request.url.path}")
    traceback.print_exc()

    return JSONResponse(
        status_code=500,
        content={
            "status": "error",
            "mensaje": "The Gateway experienced an unexpected internal failure.",
            "detalle": str(exc)
        }
    )


app.include_router(auth_empleados.router, prefix="/api/v1")
app.include_router(auth_clientes.router, prefix="/api/v1")
app.include_router(productos.router, prefix="/api/v1")
app.include_router(pedidos.router, prefix="/api/v1")
app.include_router(pedidos_movil.router, prefix="/api/v1")
app.include_router(empleados.router, prefix="/api/v1")
app.include_router(inventario.router, prefix="/api/v1")
app.include_router(movil_mesas.router, prefix="/api/v1")
app.include_router(movil_mesas.legacy_router, prefix="/api/v1")
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
