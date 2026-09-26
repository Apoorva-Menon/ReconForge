"""Configuration loads secrets without printing them."""
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    mongodb_uri: str = ""
    mongodb_db: str = "reconforge"
    model_name: str = "gemini-3.5-flash-lite"
    dataset_dir: Path = ROOT / "ReconForge_Reconciliation_Dataset"
    api_token: str = ""

    @classmethod
    def from_env(cls):
        load_dotenv(ROOT / ".env")
        path = Path(os.getenv("DATASET_DIR", "ReconForge_Reconciliation_Dataset"))
        return cls(
            mongodb_uri=os.getenv("MONGODB_URI", ""),
            mongodb_db=os.getenv("MONGODB_DB", "reconforge"),
            model_name=os.getenv("GOOGLE_MODEL", "gemini-3.5-flash-lite"),
            dataset_dir=path if path.is_absolute() else ROOT / path,
            api_token=os.getenv("RECONFORGE_API_TOKEN", ""),
        )
