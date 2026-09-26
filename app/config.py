"""Environment configuration and startup validation."""

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Settings:
    openai_api_key: str | None
    openai_model: str
    mongodb_uri: str | None
    mongodb_db: str
    demo_seed: int
    demo_dataset_size: int
    require_human_approval: bool
    enable_vector_search: bool
    log_level: str


def load_settings() -> Settings:
    """Read the documented environment variables; validate secrets at app startup."""
    return Settings(
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        openai_model=os.getenv("OPENAI_MODEL", "openai/gpt-5.6-terra"),
        mongodb_uri=os.getenv("MONGODB_URI"),
        mongodb_db=os.getenv("MONGODB_DB", "reconforge"),
        demo_seed=int(os.getenv("DEMO_SEED", "42")),
        demo_dataset_size=int(os.getenv("DEMO_DATASET_SIZE", "5000")),
        require_human_approval=os.getenv("REQUIRE_HUMAN_APPROVAL", "true").lower() == "true",
        enable_vector_search=os.getenv("ENABLE_VECTOR_SEARCH", "false").lower() == "true",
        log_level=os.getenv("LOG_LEVEL", "INFO"),
    )
