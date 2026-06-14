from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    vault_addr: str
    vault_token: str

    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "http://langfuse:3000"

    # Path to eval_thresholds.yaml, relative to the backend/ working directory.
    eval_thresholds_path: str = "../eval_thresholds.yaml"

    # Path to the Cargo Items table (class detection, D-009), relative to the
    # backend/ working directory. Gitignored data — present in dev/prod, absent
    # in CI (which never boots the lifespan).
    cargo_items_path: str = "data/raw/1.4.4.9/cargo/items.json"


def get_settings() -> Settings:
    return Settings()
