"""Argus Agent — modelos SQLAlchemy (SQLite)."""
import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    platform: Mapped[str] = mapped_column(String, nullable=False)  # web | android | ios
    # execute (padrão, roda um bdd_script) | explore (agente navega sozinho e
    # gera um bdd_script candidato — bdd_script fica "" nesse modo, nunca
    # None, pra não precisar tornar a coluna nullable).
    mode: Mapped[str] = mapped_column(String, default="execute", server_default="execute")
    app_url: Mapped[str | None] = mapped_column(String, nullable=True)
    binary_url: Mapped[str | None] = mapped_column(String, nullable=True)
    binary_auth_secret: Mapped[str | None] = mapped_column(String, nullable=True)  # nome do secret, não o valor
    bdd_script: Mapped[str] = mapped_column(Text, nullable=False)
    test_data_enc: Mapped[str] = mapped_column(Text, default="")  # massa cifrada (Fernet)
    llm_provider: Mapped[str | None] = mapped_column(String, nullable=True)
    llm_model: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="queued")
    # queued|provisioning|running|passed|failed|error|canceled
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    job_id: Mapped[str | None] = mapped_column(String, nullable=True)

    # Só usados por mode="explore" (ver src/agent/nodes.py:explore_app):
    max_actions: Mapped[int] = mapped_column(Integer, default=25, server_default="25")
    confirmed_non_production: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    generated_bdd_script: Mapped[str | None] = mapped_column(Text, nullable=True)

    scenarios_total: Mapped[int] = mapped_column(Integer, default=0)
    scenarios_passed: Mapped[int] = mapped_column(Integer, default=0)
    scenarios_failed: Mapped[int] = mapped_column(Integer, default=0)

    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)

    artifacts_dir: Mapped[str | None] = mapped_column(String, nullable=True)

    created_at: Mapped[datetime] = mapped_column(default=_utcnow)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)

    scenarios: Mapped[list["Scenario"]] = relationship(back_populates="run", cascade="all, delete-orphan")
    events: Mapped[list["RunEvent"]] = relationship(back_populates="run", cascade="all, delete-orphan")
    evidences: Mapped[list["Evidence"]] = relationship(back_populates="run", cascade="all, delete-orphan")


class Scenario(Base):
    __tablename__ = "scenarios"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    tags: Mapped[str] = mapped_column(String, default="")
    status: Mapped[str] = mapped_column(String, default="pending")
    # pending|running|passed|failed|skipped
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)

    run: Mapped["Run"] = relationship(back_populates="scenarios")
    steps: Mapped[list["Step"]] = relationship(back_populates="scenario", cascade="all, delete-orphan")


class Step(Base):
    __tablename__ = "steps"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    scenario_id: Mapped[str] = mapped_column(ForeignKey("scenarios.id"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    keyword: Mapped[str] = mapped_column(String, nullable=False)  # Given/When/Then/And/But
    text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String, default="pending")
    # pending|running|passed|failed|skipped
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)

    scenario: Mapped["Scenario"] = relationship(back_populates="steps")


class Evidence(Base):
    __tablename__ = "evidences"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), nullable=False)
    step_id: Mapped[str | None] = mapped_column(ForeignKey("steps.id"), nullable=True)
    type: Mapped[str] = mapped_column(String, nullable=False)  # screenshot|log|page_source
    label: Mapped[str] = mapped_column(String, default="")
    path: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)

    run: Mapped["Run"] = relationship(back_populates="evidences")


class RunEvent(Base):
    """Seq (id autoincrement) é a fonte de replay do SSE — substitui o
    Redis pub/sub do phalanx: um subscriber que reconecta pede `?after=seq`
    e recupera exatamente o que perdeu, sem depender de estar conectado no
    momento da publicação."""

    __tablename__ = "run_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), nullable=False)
    type: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)

    run: Mapped["Run"] = relationship(back_populates="events")


class Secret(Base):
    """Chaves de provider LLM + credenciais de auth para baixar binários mobile,
    cifradas com Fernet (src/crypto.py). Chave mestra só em ARGUS_SECRET_KEY."""

    __tablename__ = "secrets"

    name: Mapped[str] = mapped_column(String, primary_key=True)
    value_enc: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(default=_utcnow, onupdate=_utcnow)


class Setting(Base):
    """Configuração não-secreta: provider/modelo default, nome do AVD,
    device iOS, concorrência máxima, retenção de artefatos."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")


class ApiKey(Base):
    """Chaves de máquina para CI/CD (X-API-Key). A chave completa é exibida
    uma única vez na criação; só prefix + hash argon2 ficam persistidos."""

    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String, nullable=False)
    prefix: Mapped[str] = mapped_column(String, nullable=False, index=True)
    key_hash: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(nullable=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
