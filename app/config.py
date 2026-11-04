from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Todas as variáveis vêm do .env (via compose). Nada hardcoded."""

    model_config = SettingsConfigDict(extra="ignore")

    api_key: str = ""

    redis_host: str = "redis"
    redis_port: int = 6379
    redis_password: str = ""

    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_user: str = "assist"
    postgres_password: str = ""
    postgres_db: str = "assistdb"
    schema_path: str = "/app/db/init.sql"

    alerts_stream: str = "alerts_stream"
    decisions_stream: str = "decisions_stream"
    actions_stream: str = "actions_stream"
    host_exec_stream: str = "host_exec_stream"
    host_result_stream: str = "host_result_stream"
    dlq_stream: str = "agent_dlq_stream"
    worker_group: str = "assist_group"
    worker_consumer: str = ""
    stream_maxlen: int = 10000

    llm_provider: str = "auto"  # ollama | openai | auto
    llm_fallback: bool = True
    llm_timeout: float = 60.0
    ollama_url: str = "http://host.docker.internal:11434"
    ollama_model: str = "qwen2.5:3b"
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"

    short_memory_ttl: int = 86400
    short_memory_max_turns: int = 20
    recent_events_max: int = 50
    perm_memory_top_k: int = 5
    dedup_ttl: int = 300

    executor_mode: str = "dry-run"  # dry-run | live
    check_allowed_hosts: str = "postgres,redis,agent-api,host.docker.internal,localhost"


@lru_cache
def get_settings() -> Settings:
    return Settings()
