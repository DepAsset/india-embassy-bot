from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    discord_token: str
    discord_guild_id: int
    database_url: str

    request_category_id: int | None = Field(default=None, validation_alias=AliasChoices("REQUEST_CATEGORY_ID", "CATEGORY_REQUEST_ID"))
    request_channel_id: int | None = Field(default=None, validation_alias=AliasChoices("REQUEST_CHANNEL_ID", "CHANNEL_REQUEST_PARENT_ID", "CHANNEL_VERIFICATION_ID"))
    logs_channel_id: int | None = Field(default=None, validation_alias=AliasChoices("LOGS_CHANNEL_ID", "CHANNEL_SYSTEM_AUDIT_LOGS_ID", "CHANNEL_EMBASSY_REQUEST_LOGS_ID"))
    government_dashboard_channel_id: int | None = None
    government_dashboard_message_id: int | None = None
    diplomat_dashboard_channel_id: int | None = None
    diplomat_dashboard_message_id: int | None = None
    verification_dashboard_channel_id: int | None = Field(default=None, validation_alias=AliasChoices("VERIFICATION_DASHBOARD_CHANNEL_ID", "CHANNEL_VERIFICATION_ID"))
    verification_dashboard_message_id: int | None = None

    indian_citizen_role_id: int | None = Field(default=None, validation_alias=AliasChoices("ROLE_INDIAN_CITIZEN_ID", "INDIAN_CITIZEN_ROLE_ID"))
    foreign_diplomat_role_id: int | None = Field(default=None, validation_alias=AliasChoices("ROLE_FOREIGN_DIPLOMAT_ID", "FOREIGN_DIPLOMAT_ROLE_ID"))
    ambassador_role_id: int | None = Field(default=None, validation_alias=AliasChoices("ROLE_AMBASSADOR_ID", "AMBASSADOR_ROLE_ID"))

    eam_role_name: str = "EAM"
    government_notify_role_names: str = "President,Vice President,National Security Advisor,Minister,EAM"

    warera_api_base_url: str = "https://api2.warera.io"
    warera_api_profile_path: str = "/trpc/user.getUserLite"
    warera_api_full_profile_path: str = "/trpc/user.getUserById"
    warera_api_companies_path: str = "/trpc/company.getCompanies"
    warera_api_token: str | None = None

    health_host: str = "0.0.0.0"
    health_port: int = 10000

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore")


settings = Settings()
