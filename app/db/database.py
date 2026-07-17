from sqlmodel import create_engine, Session
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_engine(
    DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    connect_args={
        "login_timeout": 10,  # Fails fast within 10 seconds if Azure SQL takes too long to authenticate
        "timeout": 10        # Fails fast if any individual query gets blocked or hangs
    }
)

def get_session():
    with Session(engine) as session:
        yield session