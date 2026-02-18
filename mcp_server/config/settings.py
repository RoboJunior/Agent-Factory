from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DISCORD_BOT_TOKEN: str
    GOOGLE_API_KEY: str
    GOOGLE_GENAI_USE_VERTEXAI: str
    MCP_SERVER_URL: str
    OPENSEARCH_HOST: str
    OPENSEARCH_PORT: int
    OPENSEARCH_USERNAME: str
    OPENSEARCH_PASSWORD: str
    DISCORD_CHANNEL_ID: str

    model_config = SettingsConfigDict(env_file=".env")


@lru_cache
def get_settings():
    return Settings()
