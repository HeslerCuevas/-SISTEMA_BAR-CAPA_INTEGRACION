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
        detail="Authorization header not found",
    )


def get_current_user_payload(token: str = Depends(get_token)) -> Dict[str, Any]:
    print("\nINCOMING TOKEN DEBUG")
    print(f"RECEIVED TOKEN (first 20 characters): {token[:20]}...")
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
            print("FAILURE: Payload has no 'sub' or 'canal'")
            raise HTTPException(status_code=401, detail="Incomplete token (claims missing)")

        print("✅ TOKEN VALIDATED SUCCESSFULLY")
        print(f"USUARIO ID: {usuario_id} | CANAL: {canal}")
        return payload

    except ExpiredSignatureError:
        print("FAILURE: TOKEN EXPIRED (ExpiredSignatureError)")
        raise HTTPException(
            status_code=401,
            detail="The token has expired. Please log in again."
        )
    except JWTError as e:
        print(f"CRITICAL SIGNATURE FAILURE (JWTError): {str(e)}")

        if "Signature verification failed" in str(e):
            print("💡 RECOMMENDATION: SECRET_KEY in CORE and GATEWAY do not match.")

        raise HTTPException(
            status_code=401,
            detail=f"Validation error: {str(e)}"
        )
    except Exception as e:
        print(f"UNEXPECTED ERROR: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal error validating token")
