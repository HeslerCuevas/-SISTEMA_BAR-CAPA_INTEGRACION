import time
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from app.db.database import engine
from app.models.integration_models import TransaccionAPI
from sqlmodel import Session


class AuditLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start_time = time.time()

        request_body = await request.body()
        payload_in = request_body.decode("utf-8") if request_body else None

        response = await call_next(request)

        process_time = int((time.time() - start_time) * 1000)

        # Capturar el cuerpo de la respuesta de forma segura
        response_body = b""
        async for chunk in response.body_iterator:
            response_body += chunk

        with Session(engine) as session:
            log = TransaccionAPI(
                direccion="INBOUND",
                metodo_http=request.method,
                endpoint=str(request.url.path),
                status_code=response.status_code,
                tiempo_respuesta_ms=process_time,
                ip_origen=request.client.host,
                payload_request=payload_in,
                payload_response=response_body.decode("utf-8") if response_body else None
            )
            session.add(log)
            session.commit()

        from starlette.responses import Response
        return Response(
            content=response_body,
            status_code=response.status_code,
            headers=dict(response.headers),
            media_type=response.media_type
        )