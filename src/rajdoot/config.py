from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    discord_token: str
    discord_guild_id: int
    database_url: str

    request_category_id: int | None = None
    logs_channel_id: int | None = None
    government_dashboard_channel_id: int | None = None
    government_dashboard_message_id: int | None = None
    diplomat_dashboard_channel_id: int | None = None
    diplomat_dashboard_message_id: int | None = None

    # Support the existing Render variable name used by this deployment,
    # while also accepting the newer descriptive alias.
    indian_citizen_role_id: int | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "ROLE_INDIAN_CITIZEN_ID",
            "INDIAN_CITIZEN_ROLE_ID",
        ),
    )

    warera_api_base_url: str = "https://api.warera.io"
    warera_api_token: str | None = None

    health_host: str = "0.0.0.0"
    health_port: int = 10000

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


settings = Settings()
