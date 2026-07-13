import pytest
import time
import os
from datetime import timedelta
from unittest.mock import patch
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.mssql import UNIQUEIDENTIFIER
import uuid

@compiles(UNIQUEIDENTIFIER, "sqlite")
def compile_uniqueidentifier(type_, compiler, **kw):
    return "VARCHAR(36)"

original_bind_processor = UNIQUEIDENTIFIER.bind_processor

def patched_bind_processor(self, dialect):
    if dialect.name == "sqlite":
        def process(value):
            if value is None:
                return None
            if isinstance(value, uuid.UUID):
                return str(value)
            return str(value)
        return process
    return original_bind_processor(self, dialect)

UNIQUEIDENTIFIER.bind_processor = patched_bind_processor

# Mock out firebase to avoid initializing it during tests
patch('firebase_admin.initialize_app').start()
patch('firebase_admin.credentials.Certificate').start()

from fastapi.testclient import TestClient
from sqlmodel import SQLModel, Session, create_engine

os.environ["DATABASE_URL"] = "sqlite:///./test_int.db"
os.environ["CORE_API_URL"] = "http://fake-core-api"
os.environ["CORE_SECRET_KEY"] = "super_secret_test_key"
os.environ["GATEWAY_JWT_SECRET"] = "gateway_secret_key"

from app.db.database import get_session
from app.main import app

test_engine = create_engine("sqlite:///./test_int.db", connect_args={"check_same_thread": False}, echo=False)

from sqlalchemy import event
import datetime

@event.listens_for(test_engine, "connect")
def register_sqlite_functions(dbapi_connection, connection_record):
    dbapi_connection.create_function("GETDATE", 0, lambda: datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    dbapi_connection.create_function("sysdatetime", 0, lambda: datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f'))

def override_get_session():
    with Session(test_engine) as session:
        yield session

app.dependency_overrides[get_session] = override_get_session

@pytest.fixture(scope="function", autouse=True)
def setup_database():
    SQLModel.metadata.drop_all(test_engine)
    SQLModel.metadata.create_all(test_engine)
    yield
    SQLModel.metadata.drop_all(test_engine)
    if os.path.exists("./test_int.db"):
        try:
            os.remove("./test_int.db")
        except Exception:
            pass

@pytest.fixture(scope="function")
def db_session():
    with Session(test_engine) as session:
        yield session

@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c

# --- Custom Reporting Logic ---

def pytest_configure(config):
    config.test_results = {
        "passed": 0,
        "failed": 0,
        "skipped": 0,
        "total": 0,
        "start_time": time.time(),
        "failed_tests": []
    }

@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    report.start_time = call.start if hasattr(call, 'start') else time.time()
    report.duration = call.stop - call.start if hasattr(call, 'stop') and hasattr(call, 'start') else getattr(report, 'duration', 0)

@pytest.hookimpl(tryfirst=True)
def pytest_report_teststatus(report, config):
    if report.when == "call":
        config.test_results["total"] += 1
        
        test_name = report.nodeid.split("::")[-1].replace("_", " ").title()
        
        print("\n==================================================")
        print(f"TEST: {test_name}")
        
        duration_ms = int(report.duration * 1000)
        
        if report.passed:
            config.test_results["passed"] += 1
            print("STATUS: PASSED")
            print(f"Duration: {duration_ms} ms")
        elif report.failed:
            config.test_results["failed"] += 1
            config.test_results["failed_tests"].append(test_name)
            print("STATUS: FAILED")
            print("Reason:")
            if hasattr(report, 'longreprtext'):
                lines = report.longreprtext.split('\n')
                for line in reversed(lines):
                    if "HTTP" in line or "AssertionError" in line or "Exception" in line:
                        print(line.strip())
                        break
                else:
                    print("Test execution failed (AssertionError or Exception)")
            print(f"Duration: {duration_ms} ms")
        elif report.skipped:
            config.test_results["skipped"] += 1
            print("STATUS: SKIPPED")
            
        print("==================================================")
        
    return outcome if 'outcome' in locals() else None

def pytest_terminal_summary(terminalreporter, exitstatus, config):
    terminalreporter.writer.line("")
    terminalreporter.writer.line("====================================")
    terminalreporter.writer.line("TEST EXECUTION SUMMARY")
    terminalreporter.writer.line("====================================")
    terminalreporter.writer.line("")
    terminalreporter.writer.line(f"Total Tests: {config.test_results['total']}")
    terminalreporter.writer.line("")
    terminalreporter.writer.line(f"Passed: {config.test_results['passed']}")
    terminalreporter.writer.line("")
    terminalreporter.writer.line(f"Failed: {config.test_results['failed']}")
    terminalreporter.writer.line("")
    terminalreporter.writer.line(f"Skipped: {config.test_results['skipped']}")
    terminalreporter.writer.line("")
    
    total_duration = time.time() - config.test_results["start_time"]
    td = timedelta(seconds=int(total_duration))
    minutes, seconds = divmod(td.seconds, 60)
    terminalreporter.writer.line("Execution Time:")
    if minutes > 0:
        terminalreporter.writer.line(f"{minutes}m {seconds}s")
    else:
        terminalreporter.writer.line(f"{seconds}s")
    
    if config.test_results["failed"] > 0:
        terminalreporter.writer.line("")
        terminalreporter.writer.line("Failed Tests:")
        terminalreporter.writer.line("")
        for test in config.test_results["failed_tests"]:
            terminalreporter.writer.line(f"• {test}")
            
    terminalreporter.writer.line("")
