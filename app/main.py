import uvicorn
import traceback
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.loggin_middleware import AuditLoggingMiddleware
from app.db.database import engine
from sqlmodel import SQLModel, Session
from app.api.routers import auth, productos, pedidos, empleados, inventario, reportes
from app.services.sync_service import procesar_pedidos_pendientes, procesar_movimientos_pendientes

app = FastAPI(
    title="BAR INTEGRATION GATEWAY",
    description="Capa de Resiliencia, Seguridad y Auditoría para el Bar",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(AuditLoggingMiddleware)

scheduler = AsyncIOScheduler()


async def tarea_sincronizacion_programada():
    print("[SCHEDULER] Despertando: Revisando bandejas de salida offline...")
    with Session(engine) as session:

        pedidos_ok, pedidos_fail = await procesar_pedidos_pendientes(session)

        mov_ok, mov_fail = await procesar_movimientos_pendientes(session)

        if pedidos_ok > 0 or pedidos_fail > 0 or mov_ok > 0 or mov_fail > 0:
            print(f"[SCHEDULER] Reporte de Sincronización:")
            print(f"Pedidos: {pedidos_ok} subidos, {pedidos_fail} fallidos.")
            print(f"Movimientos: {mov_ok} subidos, {mov_fail} fallidos.")


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

@app.on_event("startup")
def on_startup():
    print("Iniciando Gateway...")
    print("Verificando/Creando esquemas en SQL Server...")
    SQLModel.metadata.create_all(engine)

    print("Iniciando programador de tareas (Background Scheduler)...")
    scheduler.add_job(tarea_sincronizacion_programada, 'interval', minutes=2)
    scheduler.start()

    print("Sistema listo y protegido.")


@app.on_event("shutdown")
def on_shutdown():
    scheduler.shutdown()

app.include_router(auth.router, prefix="/api/v1")
app.include_router(productos.router, prefix="/api/v1")
app.include_router(pedidos.router, prefix="/api/v1")
app.include_router(empleados.router, prefix="/api/v1")
app.include_router(inventario.router, prefix="/api/v1")
app.include_router(reportes.router, prefix="/api/v1")

@app.get("/", tags=["Estado del Sistema"])
async def root():
    return {
        "status": "Gateway Online",
        "mode": "Resilient",
        "scheduler": "Activo"
    }


if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8001, reload=True)