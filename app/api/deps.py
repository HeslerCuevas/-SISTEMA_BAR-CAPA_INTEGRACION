from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError, ExpiredSignatureError
from app.core.config import settings
from typing import Dict, Any, Optional

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)
token_auth_scheme = HTTPBearer(auto_error=False)


def get_token(
        token_oauth: Optional[str] = Depends(oauth2_scheme),
        token_bearer: Optional[HTTPAuthorizationCredentials] = Depends(token_auth_scheme)
) -> str:
    if token_oauth: return token_oauth
    if token_bearer: return token_bearer.credentials

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="No se encontró header de Authorization",
    )


def get_current_user_payload(token: str = Depends(get_token)) -> Dict[str, Any]:
    print("\nDEPURACIÓN DE TOKEN ENTRANTE")
    print(f"TOKEN RECIBIDO (Primeros 20 carac.): {token[:20]}...")
    print(f"USANDO LLAVE (Config): {settings.SECRET_KEY[:5]}...{settings.SECRET_KEY[-3:]}")
    print(f"ALGORITMO ESPERADO: {settings.ALGORITHM}")

    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM]
        )

        usuario_id = payload.get("sub")
        canal = payload.get("canal")

        if usuario_id is None or canal is None:
            print("FALLO: El payload no tiene 'sub' o 'canal'")
            raise HTTPException(status_code=401, detail="Token incompleto (faltan claims)")

        print("✅ TOKEN VALIDADO CORRECTAMENTE")
        print(f"USUARIO ID: {usuario_id} | CANAL: {canal}")
        return payload

    except ExpiredSignatureError:
        print("FALLO: EL TOKEN EXPIRÓ (ExpiredSignatureError)")
        raise HTTPException(
            status_code=401,
            detail="El token ha expirado. Haz login de nuevo."
        )
    except JWTError as e:
        print(f"FALLO CRÍTICO DE FIRMA (JWTError): {str(e)}")

        if "Signature verification failed" in str(e):
            print("💡 RECOMENDACIÓN: La SECRET_KEY en el CORE y el GATEWAY no coinciden.")

        raise HTTPException(
            status_code=401,
            detail=f"Error de validación: {str(e)}"
        )
    except Exception as e:
        print(f"ERROR INESPERADO: {str(e)}")
        raise HTTPException(status_code=500, detail="Error interno validando token")

