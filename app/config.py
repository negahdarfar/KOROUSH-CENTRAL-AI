from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    github_token: str = ""
    llm_provider: str = "legacy"
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    avalai_base_url: str = "https://api.avalai.ir/v1"
    avalai_api_key: str = ""
    avalai_model: str = ""
    allowed_repos: str = ""
    port: int = 8000
    admin_api_key: str = ""
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    @property
    def repo_allowlist(self) -> set[str]:
        return {x.strip() for x in self.allowed_repos.split(",") if x.strip()}

    @property
    def active_llm(self) -> dict:
        """Resolve the selected provider without exposing credentials."""
        provider = self.llm_provider.strip().lower()
        if provider == "avalai":
            return {
                "provider": "avalai",
                "base_url": self.avalai_base_url.rstrip("/"),
                "api_key": self.avalai_api_key,
                "model": self.avalai_model,
            }
        if provider in {"legacy", "custom", "openai-compatible"}:
            return {
                "provider": "legacy",
                "base_url": self.llm_base_url.rstrip("/"),
                "api_key": self.llm_api_key,
                "model": self.llm_model,
            }
        return {"provider": provider, "base_url": "", "api_key": "", "model": ""}


settings = Settings()
