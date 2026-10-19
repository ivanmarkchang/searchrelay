"""No credentials in config: keys are read only from named environment variables."""
import os
import json
import tempfile
from pathlib import Path

try:
    import tomllib
except ImportError:
    import tomli as tomllib

from pydantic import Field, model_validator

from .models import Model

PROVIDERS = {"tavily", "firecrawl", "serpapi", "you"}


def config_dir() -> Path:
    return Path(os.environ.get("SEARCHRELAY_HOME", Path.home() / ".config" / "searchrelay"))


class ProviderConfig(Model):
    enabled: bool = False
    free_plan_confirmed: bool = False
    key_env: str | None = None
    daily_limit: int = Field(default=50, ge=0)
    monthly_limit: int = Field(default=200, ge=0)
    min_interval_seconds: float = Field(default=6, ge=1, le=3600)
    cache_allowed: bool = False


class Config(Model):
    providers: dict[str, ProviderConfig] = Field(default_factory=dict)
    max_attempts: int = Field(default=3, ge=1, le=8)
    deadline_seconds: float = Field(default=20, ge=1, le=60)
    cache_ttl_seconds: int = Field(default=0, ge=0, le=86400)
    retention_days: int = Field(default=7, ge=0, le=90)

    @model_validator(mode="after")
    def known_providers(self):
        if set(self.providers) - PROVIDERS:
            raise ValueError("unknown provider; allowed: tavily, firecrawl, serpapi, you")
        return self


def load_config(path: Path | None = None) -> Config:
    path = path or config_dir() / "config.toml"
    if not path.exists():
        return Config()
    with path.open("rb") as source:
        return Config.model_validate(tomllib.load(source))


def save_config(config: Config, path: Path) -> None:
    """Atomically persist validated settings, never credentials."""
    lines = ["# Managed by SearchRelay. Provider order defines fallback order."]
    def append_fields(values):
        for key, value in values.items():
            if value is not None:
                literal = str(value).lower() if isinstance(value, bool) else json.dumps(value)
                lines.append(f"{key} = {literal}")
    data = config.model_dump()
    append_fields({key: value for key, value in data.items() if key != "providers"})
    for name, values in data["providers"].items():
        lines.append(f"\n[providers.{name}]")
        append_fields(values)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temp = tempfile.mkstemp(prefix=".settings-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as output:
            output.write("\n".join(lines) + "\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


TEMPLATE = '''# SearchRelay never upgrades accounts or purchases credits.
# Use ONLY free accounts with no payment method, paid subscription or auto-renewal.
# Mark free_plan_confirmed=true only after checking the provider dashboard.
# Provider order below is the fallback order. Disabled providers are skipped.
max_attempts = 3
deadline_seconds = 20
cache_ttl_seconds = 0
retention_days = 7

[providers.tavily]
enabled = false
free_plan_confirmed = false
key_env = "TAVILY_API_KEY"
daily_limit = 50
monthly_limit = 900
min_interval_seconds = 2

[providers.firecrawl]
enabled = false
free_plan_confirmed = false
key_env = "FIRECRAWL_API_KEY"
daily_limit = 30
monthly_limit = 400
min_interval_seconds = 6

[providers.serpapi]
enabled = false
free_plan_confirmed = false
key_env = "SERPAPI_API_KEY"
daily_limit = 15
monthly_limit = 200
min_interval_seconds = 72

[providers.you]
enabled = false
daily_limit = 80
monthly_limit = 2000
min_interval_seconds = 6
'''
