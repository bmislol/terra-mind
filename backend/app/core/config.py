from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    vault_addr: str
    vault_token: str


def get_settings() -> Settings:
    return Settings()
