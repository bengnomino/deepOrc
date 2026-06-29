"""Gateway agent configuration."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    agent_token: str = "change-me"
    wg_interface: str = "wg0"
    listen_host: str = "0.0.0.0"
    listen_port: int = 8081
    orch_allowed_ip: str = "10.10.0.1"
    net_interface: str = "eth0"
    nft_suspend_table: str = "inet wg_suspend"


def get_agent_settings() -> AgentSettings:
    return AgentSettings()
