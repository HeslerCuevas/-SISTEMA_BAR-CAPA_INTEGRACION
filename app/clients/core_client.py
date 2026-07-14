import httpx
import logging
from typing import Optional, Dict, Any
from app.core.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("CoreClient")


class CoreClient:
    def __init__(self):
        self.base_url = settings.CORE_URL
        self.gateway_token = settings.CORE_SECRET_KEY
        self.timeout = httpx.Timeout(10.0, connect=5.0)

    def _get_headers(self, extra_headers: Optional[Dict] = None) -> Dict[str, str]:
        headers = {"X-Gateway-Token": self.gateway_token}
        if extra_headers:
            headers.update(extra_headers)
        return headers

    async def get(self, endpoint: str, headers: Optional[Dict] = None, params: Optional[Dict] = None) -> Optional[Any]:
        url = f"{self.base_url}{endpoint}"
        final_headers = self._get_headers(headers)

        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            try:
                response = await client.get(url, headers=final_headers, params=params)

                if response.status_code == 422:
                    logger.error(f"[DEBUG 422] El CORE rechazó los datos (GET). Detalle: {response.json()}")
                    return None

                response.raise_for_status()
                return response.json()

            except httpx.ConnectError:
                logger.error(f"[MODO OFFLINE] El CORE está APAGADO o inaccesible en {url}")
                return None
            except httpx.ReadTimeout:
                logger.error(f"[MODO OFFLINE] El CORE está DEMASIADO LENTO (Timeout) en {url}")
                return None
            except httpx.HTTPStatusError as e:
                logger.error(f"[ERROR CORE] El CORE devolvió un error {e.response.status_code} en {url}")
                return None
            except Exception as e:
                logger.critical(f"[ERROR CRÍTICO] Fallo inesperado comunicándose con el CORE: {str(e)}")
                return None

    async def post(self, endpoint: str, data: Optional[Dict[str, Any]] = None, json: Optional[Dict[str, Any]] = None, headers: Optional[Dict] = None, params: Optional[Dict] = None) -> Optional[Dict[str, Any]]:
        url = f"{self.base_url}{endpoint}"
        final_headers = self._get_headers(headers)

        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            try:
                response = await client.post(url, data=data, json=json, headers=final_headers, params=params)

                if response.status_code == 422:
                    logger.error(f"[DEBUG 422] El CORE rechazó el POST. Detalle: {response.json()}")
                    return None

                response.raise_for_status()
                return response.json()

            except (httpx.ConnectError, httpx.ReadTimeout):
                logger.warning(
                    f"[OUTBOX PATTERN] CORE inalcanzable. El dato (POST) deberá guardarse en el búfer local.")
                return None
            except httpx.HTTPStatusError as e:
                status_code = e.response.status_code
                # For 4xx errors, return the response body so callers can surface the detail to the client.
                # For 5xx errors, treat as CORE unavailable.
                if 400 <= status_code < 500:
                    logger.warning(f"[ERROR CORE] POST a {url} error de negocio {status_code}: {e.response.text}")
                    try:
                        return e.response.json()
                    except Exception:
                        return {"detail": e.response.text}
                logger.error(f"[ERROR CORE] POST a {url} falló con estado {status_code}: {e.response.text}")
                return None
            except Exception as e:
                logger.critical(f"[ERROR CRÍTICO] Fallo inesperado en POST: {str(e)}")
                return None

    async def patch(self, endpoint: str, data: Optional[Dict[str, Any]] = None, json: Optional[Dict[str, Any]] = None, headers: Optional[Dict] = None) -> Optional[Dict[str, Any]]:
        url = f"{self.base_url}{endpoint}"
        final_headers = self._get_headers(headers)

        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            try:
                response = await client.patch(url, data=data, json=json, headers=final_headers)

                if response.status_code == 422:
                    logger.error(f"[DEBUG 422] El CORE rechazó el PATCH. Detalle: {response.json()}")
                    return None

                response.raise_for_status()
                return response.json()

            except (httpx.ConnectError, httpx.ReadTimeout):
                logger.warning(
                    f"[OUTBOX PATTERN] CORE inalcanzable. El dato (PATCH) deberá guardarse en el búfer local.")
                return None
            except httpx.HTTPStatusError as e:
                status_code = e.response.status_code
                if 400 <= status_code < 500:
                    logger.warning(f"[ERROR CORE] PATCH a {url} error de negocio {status_code}: {e.response.text}")
                    try:
                        return e.response.json()
                    except Exception:
                        return {"detail": e.response.text}
                logger.error(f"[ERROR CORE] PATCH a {url} falló con estado {status_code}: {e.response.text}")
                return None
            except Exception as e:
                logger.critical(f"[ERROR CRÍTICO] Fallo inesperado en PATCH: {str(e)}")
                return None

    async def put(self, endpoint: str, data: Optional[Dict[str, Any]] = None, json: Optional[Dict[str, Any]] = None, headers: Optional[Dict] = None) -> Optional[Dict[str, Any]]:
        url = f"{self.base_url}{endpoint}"
        final_headers = self._get_headers(headers)

        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            try:
                response = await client.put(url, data=data, json=json, headers=final_headers)

                if response.status_code == 422:
                    logger.error(f"[DEBUG 422] El CORE rechazó el PUT. Detalle: {response.json()}")
                    return None

                response.raise_for_status()
                return response.json()

            except (httpx.ConnectError, httpx.ReadTimeout):
                logger.warning(f"[OUTBOX PATTERN] CORE inalcanzable (PUT).")
                return None
            except httpx.HTTPStatusError as e:
                status_code = e.response.status_code
                if 400 <= status_code < 500:
                    logger.warning(f"[ERROR CORE] PUT a {url} error de negocio {status_code}: {e.response.text}")
                    try:
                        return e.response.json()
                    except Exception:
                        return {"detail": e.response.text}
                logger.error(f"[ERROR CORE] PUT a {url} falló con estado {status_code}: {e.response.text}")
                return None
            except Exception as e:
                logger.critical(f"[ERROR CRÍTICO] Fallo inesperado en PUT: {str(e)}")
                return None

    async def delete(self, endpoint: str, headers: Optional[Dict] = None, params: Optional[Dict] = None) -> Optional[
        Dict[str, Any]]:
        url = f"{self.base_url}{endpoint}"
        final_headers = self._get_headers(headers)

        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            try:
                response = await client.delete(url, headers=final_headers, params=params)

                if response.status_code == 422:
                    logger.error(f"[DEBUG 422] El CORE rechazó el DELETE. Detalle: {response.json()}")
                    return None

                response.raise_for_status()
                if response.status_code == 204:
                    return {"mensaje": "Eliminado exitosamente"}

                return response.json()

            except (httpx.ConnectError, httpx.ReadTimeout):
                logger.warning(f"[OUTBOX PATTERN] CORE inalcanzable (DELETE).")
                return None
            except httpx.HTTPStatusError as e:
                logger.error(
                    f"[ERROR CORE] DELETE a {url} falló con estado {e.response.status_code}: {e.response.text}")
                return None
            except Exception as e:
                logger.critical(f"[ERROR CRÍTICO] Fallo inesperado en DELETE: {str(e)}")
                return None


core_client = CoreClient()