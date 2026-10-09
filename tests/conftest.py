import mongomock
import pytest

import app.main as app_module
from app.db import mongo


@pytest.fixture(autouse=True)
def isolated_database(monkeypatch):
    mock_client = mongomock.MongoClient()
    monkeypatch.setattr(mongo, "_database", mock_client["test_attendance"])
    app_module.ensure_indexes()
    yield
    mock_client.close()
