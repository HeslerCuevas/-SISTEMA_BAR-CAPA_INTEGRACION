import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import SQLModel

from app.core.loggin_middleware import AuditLoggingMiddleware
from app.db.database import engine
from app.api.routers import auth

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

@app.on_event("startup")
def on_startup():
    print("Iniciando Gateway...")
    print("Verificando/Creando esquemas en SQL Server (Integration_Gateway_DB)...")
    SQLModel.metadata.create_all(engine)
    print("Base de datos lista.")


app.include_router(auth.router, prefix="/api/v1")

@app.get("/", tags=["Estado del Sistema"])
async def root():
    return {
        "status": "Gateway Online",
        "mode": "Resilient",
        "message": "Capa de Integración activa y esperando conexiones."
    }

if __name__ == "__main__":
    # Usamos el puerto 8001 para no chocar con el CORE que usa el 8000
    uvicorn.run("main:app", host="127.0.0.1", port=8001, reload=True)