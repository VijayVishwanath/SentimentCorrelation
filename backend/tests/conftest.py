import os
import tempfile
from pathlib import Path

# Isolated database for the test session — must be set before the app is imported.
_TMP = Path(tempfile.mkdtemp(prefix="dex_sentinel_test_"))
os.environ["DEX_DATABASE_URL"] = f"sqlite:///{(_TMP / 'test.db').as_posix()}"
os.environ["DEX_LLM_PROVIDER"] = "template"
os.environ.pop("ANTHROPIC_API_KEY", None)

import pytest  # noqa: E402

from app.data.store import init_store  # noqa: E402


@pytest.fixture(scope="session")
def store():
    return init_store(force_seed=True)


@pytest.fixture(scope="session")
def client(store):
    from fastapi.testclient import TestClient

    from app.main import app
    with TestClient(app) as c:
        yield c
