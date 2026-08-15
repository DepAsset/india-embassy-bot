alter table discord_configuration
    add column if not exists verification_dashboard_channel_id bigint,
    add column if not exists verification_dashboard_message_id bigint;
