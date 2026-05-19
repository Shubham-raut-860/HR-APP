from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_health_endpoint_returns_healthy() -> None:
    with patch("app.database.engine", new=MagicMock()), patch(
        "app.main._run_startup_schema_guard", new=AsyncMock()
    ), patch("app.main._run_startup_database_health_checks", new=AsyncMock()):
        from app.main import app

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
