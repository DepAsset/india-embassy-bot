from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    discord_token: str
    discord_guild_id: int

    role_president_id: int
    role_vice_president_id: int
    role_nsa_id: int
    role_minister_id: int
    role_eam_id: int
    role_foreign_secretary_id: int
    role_ambassador_id: int
    role_foreign_diplomat_id: int
    role_foreigner_id: int
    role_indian_citizen_id: int
    role_nri_id: int

    category_embassy_1_id: int
    category_embassy_2_id: int
    category_embassy_graveyard_id: int

    channel_embassy_management_id: int
    channel_foreign_diplomat_dashboard_id: int
    channel_verification_id: int
    channel_request_parent_id: int
    channel_embassy_request_logs_id: int
    channel_system_audit_logs_id: int

    mongodb_uri: str
    mongodb_database: str
    warera_api_base: str

    health_host: str = "0.0.0.0"
    health_port: int = 10000


settings = Settings()
