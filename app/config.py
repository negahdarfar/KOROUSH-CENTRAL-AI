from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    github_token: str = ""
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    allowed_repos: str = ""
    port: int = 8000
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    @property
    def repo_allowlist(self) -> set[str]:
        return {x.strip() for x in self.allowed_repos.split(",") if x.strip()}

settings = Settings()
