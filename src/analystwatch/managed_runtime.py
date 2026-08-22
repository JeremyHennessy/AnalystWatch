from __future__ import annotations

import os
from dataclasses import dataclass

from .auth import WorkspaceMembership, WorkspaceRole
from .auth_storage import PostgresMembershipStore
from .email_delivery import EmailDestination, ResendEmailAdapter
from .postgres_storage import PostgresStorage
from .workspace import validate_workspace_id


@dataclass(frozen=True)
class ManagedRuntimeConfig:
    postgres_dsn: str
    workspace_id: str
    auth_secret: str
    bootstrap_admin_user_id: str
    resend_api_key: str
    email_from: str
    email_to: tuple[str, ...]
    public_base_url: str

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "ManagedRuntimeConfig":
        values = env if env is not None else os.environ

        def require(name: str) -> str:
            value = values.get(name)
            if value is None or not value or value != value.strip():
                raise ValueError(f"{name} must be configured as a trimmed non-empty secret/value")
            return value

        raw_recipients = require("ANALYSTWATCH_EMAIL_TO")
        recipients = tuple(item.strip() for item in raw_recipients.split(",") if item.strip())
        if not recipients:
            raise ValueError("ANALYSTWATCH_EMAIL_TO must contain at least one recipient")

        return cls(
            postgres_dsn=require("ANALYSTWATCH_POSTGRES_DSN"),
            workspace_id=validate_workspace_id(require("ANALYSTWATCH_WORKSPACE_ID")),
            auth_secret=require("ANALYSTWATCH_AUTH_SECRET"),
            bootstrap_admin_user_id=require("ANALYSTWATCH_BOOTSTRAP_ADMIN_USER_ID"),
            resend_api_key=require("ANALYSTWATCH_RESEND_API_KEY"),
            email_from=require("ANALYSTWATCH_EMAIL_FROM"),
            email_to=recipients,
            public_base_url=require("ANALYSTWATCH_PUBLIC_BASE_URL"),
        )

    def email_adapter(self) -> ResendEmailAdapter:
        return ResendEmailAdapter(
            self.resend_api_key,
            EmailDestination(
                from_address=self.email_from,
                to_addresses=self.email_to,
                base_url=self.public_base_url,
            ),
        )


@dataclass(frozen=True)
class ManagedRuntimeReadiness:
    workspace_id: str
    storage_id: str
    admin_user_id: str
    source_count: int
    observation_count: int
    candidate_count: int
    delivery_attempt_count: int


def prepare_managed_runtime(config: ManagedRuntimeConfig) -> ManagedRuntimeReadiness:
    """Initialize and verify the managed PostgreSQL runtime before serving traffic."""
    monitoring = PostgresStorage(config.postgres_dsn, config.workspace_id)
    monitoring.initialize()

    memberships = PostgresMembershipStore(config.postgres_dsn)
    memberships.initialize()
    current = memberships.get_membership(config.workspace_id, config.bootstrap_admin_user_id)
    if current is None:
        memberships.upsert_membership(
            WorkspaceMembership(
                workspace_id=config.workspace_id,
                user_id=config.bootstrap_admin_user_id,
                role=WorkspaceRole.ADMIN,
            )
        )
    elif current.role != WorkspaceRole.ADMIN:
        raise ValueError("Configured bootstrap principal exists but is not an Admin")

    verification = monitoring.verify()
    if not verification.integrity_ok or not verification.storage_id:
        raise RuntimeError(verification.integrity_message)

    return ManagedRuntimeReadiness(
        workspace_id=config.workspace_id,
        storage_id=verification.storage_id,
        admin_user_id=config.bootstrap_admin_user_id,
        source_count=verification.source_count,
        observation_count=verification.observation_count,
        candidate_count=verification.notification_candidate_count,
        delivery_attempt_count=verification.delivery_attempt_count,
    )
