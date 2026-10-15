"""Settings from the project .env, plus the OpenAI key file it points to."""

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        key, sep, value = line.strip().partition("=")
        if sep and not key.startswith("#"):
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


_load(ROOT / ".env")
if os.environ.get("PATHMEMORY_ENV_FILE"):
    _load(Path(os.environ["PATHMEMORY_ENV_FILE"]))


@dataclass(frozen=True)
class Settings:
    root: Path = ROOT
    gitea_url: str = os.environ.get("GITEA_URL", "http://localhost:3300")
    falkordb_host: str = os.environ.get("FALKORDB_HOST", "localhost")
    falkordb_port: int = int(os.environ.get("FALKORDB_PORT", "6391"))
    openai_model: str = os.environ.get("OPENAI_MODEL", "gpt-6-luna")


settings = Settings()
