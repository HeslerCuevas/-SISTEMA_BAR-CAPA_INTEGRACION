import os
import httpx
import logging
from typing import Optional, Dict, Any
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("CoreClient")


class CoreClient:
    def __init__(self):
        self.base_url = os.getenv("CORE_URL")

        self.gateway_token = os.getenv("CORE_SECRET_KEY")

        self.timeout = httpx.Timeout(5.0, connect=2.0)

    async def get(self, endpoint: str, headers: Optional[Dict] = None, params: Optional[Dict] = None) -> Optional[Any]:
        url = f"{self.base_url}{endpoint}"

        headers = {"X-Gateway-Token": self.gateway_token}

        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            try:
                response = await client.get(url, headers=headers, params=params)

                if response.status_code == 422:
                    logger.error(f"[DEBUG 422] El CORE rechazó los datos. Detalle: {response.json()}")
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

    async def post(self, endpoint: str, data: Dict[str, Any], headers: Optional[Dict] = None) -> Optional[
        Dict[str, Any]]:
        url = f"{self.base_url}{endpoint}"

        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            try:
                response = await client.post(url, json=data, headers=headers)

                if response.status_code == 422:
                    logger.error(f"[DEBUG 422] El CORE rechazó el POST. Detalle: {response.json()}")
                    return None

                response.raise_for_status()
                return response.json()

            except (httpx.ConnectError, httpx.ReadTimeout):
                logger.warning(f"[OUTBOX PATTERN] CORE inalcanzable. El dato deberá guardarse en el búfer local.")
                return None
            except httpx.HTTPStatusError as e:
                logger.error(f"[ERROR CORE] POST a {url} falló con estado {e.response.status_code}: {e.response.text}")
                return None


# SINGLETON
core_client = CoreClient()