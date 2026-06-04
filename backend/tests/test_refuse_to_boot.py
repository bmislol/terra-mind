import pytest

from app.core.config import Settings
from app.infra.vault import load_secrets


def test_vault_unreachable_raises() -> None:
    settings = Settings(
        database_url="postgresql+asyncpg://x:x@localhost:5432/x",
        vault_addr="http://localhost:19999",
        vault_token="fake-token",
    )
    with pytest.raises(RuntimeError, match="REFUSING TO BOOT"):
        load_secrets(settings, timeout=1)
