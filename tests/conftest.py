from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def app():
    """Fresh FastAPI instance per test — no shared state."""
    return create_app()


@pytest.fixture
def client(app):
    """Synchronous test client wrapping the app factory."""
    return TestClient(app)


@pytest.fixture
def mock_bedrock():
    """
    Patches boto3.client so no real AWS calls are made.
    Tests that need specific Bedrock responses should configure mock_bedrock.invoke_model.return_value.
    """
    with patch("boto3.client") as mock:
        mock_client = MagicMock()
        mock.return_value = mock_client
        yield mock_client


@pytest.fixture
def mock_redis():
    """
    Patches get_redis_client so tests do not need a running Redis.
    Tests that need specific Redis responses should configure mock_redis.get.return_value etc.
    """
    with patch("app.redis_client.get_redis_client") as mock:
        mock_client = AsyncMock()
        mock.return_value = mock_client
        yield mock_client


@pytest.fixture
def mock_db_session():
    """
    Patches get_session so tests do not need a running PostgreSQL.
    Use this for unit tests; integration tests should use TEST_DATABASE_URL from .env.
    """
    with patch("app.database.get_session") as mock:
        session = AsyncMock()
        mock.return_value.__aenter__ = AsyncMock(return_value=session)
        mock.return_value.__aexit__ = AsyncMock(return_value=False)
        yield session


@pytest.fixture
def mock_kafka_producer():
    """
    Patches the Kafka producer so tests do not need a running Kafka broker.
    Tests should assert on mock_kafka_producer.send.call_args to verify event payloads.
    """
    with patch("kafka.KafkaProducer") as mock:
        producer = MagicMock()
        mock.return_value = producer
        yield producer
