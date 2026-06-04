import hvac
from pydantic import BaseModel

from app.core.config import Settings


class AppSecrets(BaseModel, frozen=True):
    anthropic_api_key: str
    jwt_signing_key: str


def load_secrets(settings: Settings, *, timeout: int = 5) -> AppSecrets:
    client = hvac.Client(
        url=settings.vault_addr,
        token=settings.vault_token,
        timeout=timeout,
    )
    try:
        authenticated = client.is_authenticated()
    except Exception as exc:
        raise RuntimeError(
            f"REFUSING TO BOOT: Vault unreachable at {settings.vault_addr} — {exc}"
        ) from exc

    if not authenticated:
        raise RuntimeError(
            f"REFUSING TO BOOT: Vault at {settings.vault_addr} rejected token"
        )

    try:
        anthropic_resp = client.secrets.kv.v2.read_secret_version(
            path="terra-mind/anthropic",
            mount_point="secret",
            raise_on_deleted_version=True,
        )
        jwt_resp = client.secrets.kv.v2.read_secret_version(
            path="terra-mind/jwt",
            mount_point="secret",
            raise_on_deleted_version=True,
        )
    except Exception as exc:
        raise RuntimeError(
            f"REFUSING TO BOOT: could not read secrets from Vault — {exc}"
        ) from exc

    return AppSecrets(
        anthropic_api_key=anthropic_resp["data"]["data"]["api_key"],
        jwt_signing_key=jwt_resp["data"]["data"]["signing_key"],
    )
