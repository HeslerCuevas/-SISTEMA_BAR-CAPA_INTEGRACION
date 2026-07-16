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
                    logger.error(f"[DEBUG 422] CORE rejected the data (GET). Details: {response.json()}")
                    return None

                response.raise_for_status()
                return response.json()

            except httpx.ConnectError:
                logger.error(f"[OFFLINE MODE] CORE is DOWN or inaccessible at {url}")
                return None
            except httpx.ReadTimeout:
                logger.error(f"[OFFLINE MODE] CORE is TOO SLOW (timeout) at {url}")
                return None
            except httpx.HTTPStatusError as e:
                logger.error(f"[CORE ERROR] CORE returned error {e.response.status_code} at {url}")
                return None
            except Exception as e:
                logger.critical(f"[CRITICAL ERROR] Unexpected failure communicating with CORE: {str(e)}")
                return None

    async def post(self, endpoint: str, data: Optional[Dict[str, Any]] = None, json: Optional[Dict[str, Any]] = None, headers: Optional[Dict] = None, params: Optional[Dict] = None) -> Optional[Dict[str, Any]]:
        url = f"{self.base_url}{endpoint}"
        final_headers = self._get_headers(headers)

        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            try:
                response = await client.post(url, data=data, json=json, headers=final_headers, params=params)

                if response.status_code == 422:
                    logger.error(f"[DEBUG 422] CORE rejected the POST. Details: {response.json()}")
                    return None

                response.raise_for_status()
                return response.json()

            except (httpx.ConnectError, httpx.ReadTimeout):
                logger.warning(
                    f"[OUTBOX PATTERN] CORE unreachable. The data (POST) will be saved in the local buffer.")
                return None
            except httpx.HTTPStatusError as e:
                status_code = e.response.status_code
                # For 4xx errors, return the response body so callers can surface the detail to the client.
                # Preserve CORE 5xx details too (for example, an SMTP outage)
                # instead of replacing them with a generic CORE error.
                if 400 <= status_code < 500:
                    logger.warning(f"[CORE ERROR] POST to {url} business error {status_code}: {e.response.text}")
                    try:
                        payload = e.response.json()
                        if isinstance(payload, dict):
                            payload.setdefault("_status_code", status_code)
                        return payload
                    except Exception:
                        return {"detail": e.response.text, "_status_code": status_code}
                try:
                    payload = e.response.json()
                    if isinstance(payload, dict):
                        payload.setdefault("_status_code", status_code)
                        return payload
                except Exception:
                    pass
                logger.error(f"[CORE ERROR] POST to {url} failed with status {status_code}: {e.response.text}")
                return None
            except Exception as e:
                logger.critical(f"[CRITICAL ERROR] Unexpected failure in POST: {str(e)}")
                return None

    async def patch(self, endpoint: str, data: Optional[Dict[str, Any]] = None, json: Optional[Dict[str, Any]] = None, headers: Optional[Dict] = None) -> Optional[Dict[str, Any]]:
        url = f"{self.base_url}{endpoint}"
        final_headers = self._get_headers(headers)

        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            try:
                response = await client.patch(url, data=data, json=json, headers=final_headers)

                if response.status_code == 422:
                    logger.error(f"[DEBUG 422] CORE rejected the PATCH. Details: {response.json()}")
                    return None

                response.raise_for_status()
                return response.json()

            except (httpx.ConnectError, httpx.ReadTimeout):
                logger.warning(
                    f"[OUTBOX PATTERN] CORE unreachable. The data (PATCH) will be saved in the local buffer.")
                return None
            except httpx.HTTPStatusError as e:
                status_code = e.response.status_code
                if 400 <= status_code < 500:
                    logger.warning(f"[CORE ERROR] PATCH to {url} business error {status_code}: {e.response.text}")
                    try:
                        payload = e.response.json()
                        if isinstance(payload, dict):
                            payload.setdefault("_status_code", status_code)
                        return payload
                    except Exception:
                        return {"detail": e.response.text, "_status_code": status_code}
                logger.error(f"[CORE ERROR] PATCH to {url} failed with status {status_code}: {e.response.text}")
                return None
            except Exception as e:
                logger.critical(f"[CRITICAL ERROR] Unexpected failure in PATCH: {str(e)}")
                return None

    async def put(self, endpoint: str, data: Optional[Dict[str, Any]] = None, json: Optional[Dict[str, Any]] = None, headers: Optional[Dict] = None) -> Optional[Dict[str, Any]]:
        url = f"{self.base_url}{endpoint}"
        final_headers = self._get_headers(headers)

        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            try:
                response = await client.put(url, data=data, json=json, headers=final_headers)

                if response.status_code == 422:
                    logger.error(f"[DEBUG 422] CORE rejected the PUT. Details: {response.json()}")
                    return None

                response.raise_for_status()
                return response.json()

            except (httpx.ConnectError, httpx.ReadTimeout):
                logger.warning(f"[OUTBOX PATTERN] CORE unreachable (PUT).")
                return None
            except httpx.HTTPStatusError as e:
                status_code = e.response.status_code
                if 400 <= status_code < 500:
                    logger.warning(f"[CORE ERROR] PUT to {url} business error {status_code}: {e.response.text}")
                    try:
                        payload = e.response.json()
                        if isinstance(payload, dict):
                            payload.setdefault("_status_code", status_code)
                        return payload
                    except Exception:
                        return {"detail": e.response.text, "_status_code": status_code}
                logger.error(f"[CORE ERROR] PUT to {url} failed with status {status_code}: {e.response.text}")
                return None
            except Exception as e:
                logger.critical(f"[CRITICAL ERROR] Unexpected failure in PUT: {str(e)}")
                return None

    async def delete(self, endpoint: str, headers: Optional[Dict] = None, params: Optional[Dict] = None) -> Optional[
        Dict[str, Any]]:
        url = f"{self.base_url}{endpoint}"
        final_headers = self._get_headers(headers)

        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            try:
                response = await client.delete(url, headers=final_headers, params=params)

                if response.status_code == 422:
                    logger.error(f"[DEBUG 422] CORE rejected the DELETE. Details: {response.json()}")
                    return None

                response.raise_for_status()
                if response.status_code == 204:
                    return {"mensaje": "Eliminado exitosamente"}

                return response.json()

            except (httpx.ConnectError, httpx.ReadTimeout):
                logger.warning(f"[OUTBOX PATTERN] CORE unreachable (DELETE).")
                return None
            except httpx.HTTPStatusError as e:
                logger.error(
                    f"[ERROR CORE] DELETE a {url} falló con estado {e.response.status_code}: {e.response.text}")
                return None
            except Exception as e:
                logger.critical(f"[CRITICAL ERROR] Unexpected failure in DELETE: {str(e)}")
                return None


core_client = CoreClient()
