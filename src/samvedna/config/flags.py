"""Runtime feature flags and operational settings.

Every setting is a field on this model so a single `.env` controls all of it —
half the knobs silently ignoring the file they appear to live in is worse than
having no knob at all.
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

RunMode = Literal["live", "replay"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_prefix="SAMVEDNA_", extra="ignore"
    )

    # --- transport ----------------------------------------------------------
    host: str = "127.0.0.1"
    port: int = 8090
    allowed_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])
    database_url: str = "sqlite+aiosqlite:///./samvedna.db"

    # --- run ----------------------------------------------------------------
    # REPLAY runs the whole pipeline from synthetic fixtures with no connector
    # access at all (PART 1, constraint 7). It is the default so that no demo can
    # accidentally depend on live service records.
    mode: RunMode = "replay"
    fixtures_dir: str = "fixtures"

    # --- privacy ------------------------------------------------------------
    # In production this is an HSM/KMS handle. In REPLAY it is a local secret so
    # the pipeline is exercisable offline; pseudonymisation is identical either way.
    pseudonym_salt: str = "replay-salt-not-for-production"
    hsm_endpoint: str | None = None
    differential_privacy: bool = True

    # --- analytics ----------------------------------------------------------
    # When the tabular model is unavailable the pipeline still runs: the risk
    # score is only an input to the gates, never the decision. Stage 5 degrades,
    # it does not fail (PART 8.8).
    risk_model: Literal["auto", "lightgbm", "off"] = "auto"
    model_dir: str = "artefacts/models"
    sequence_model: Literal["auto", "transformer", "off"] = "auto"
    survival_model: Literal["auto", "cox", "off"] = "auto"

    # --- reviewers ----------------------------------------------------------
    # Deliberately absent: any external LLM endpoint. PART 1 and PART 10 forbid
    # external processing of this data class. Reviewers are on-prem and rule- or
    # retrieval-based.
    reviewer_timeout_s: float = 20.0
    # Escalation is frozen to MONITOR-only when Confounder Check is unavailable.
    freeze_on_reviewer_failure: bool = True

    # --- consent text -------------------------------------------------------
    # Allow consent to be recorded against a translation that has not yet been
    # checked by a native speaker. OFF by default, and a deployment that leaves
    # it on is misconfigured. It exists because a pilot unit reading a draft is
    # how a draft becomes reviewed.
    consent_pilot_mode: bool = False
    locale_dir: str = "web/i18n/locales"

    # --- disclosure ---------------------------------------------------------
    oidc_issuer: str | None = None  # Keycloak in production; local dev signer otherwise
    token_ttl_s: int = 3600


_settings: Settings | None = None


def settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings() -> None:
    """Test hook: drop the cached settings so env changes take effect."""
    global _settings
    _settings = None
