from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from sqlmodel import Session
from app.db.database import get_session
from app.core.security import SECRET_KEY, ALGORITHM
from typing import Dict, Any

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


def get_current_user_payload(token: str = Depends(oauth2_scheme)) -> Dict[str, Any]:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="No se pudieron validar las credenciales o el token ha expirado",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        usuario_id: str = payload.get("sub")
        canal: str = payload.get("canal")

        if usuario_id is None or canal is None:
            raise credentials_exception

        return payload

    except JWTError:
        raise credentials_exception


def get_current_empleado_caja(payload: dict = Depends(get_current_user_payload)):
    if payload.get("canal") != "CAJA":
        raise HTTPException(status_code=403, detail="Acceso denegado. Solo permitido para Caja (WPF).")
    return payload