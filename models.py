"""SQLModel für Kubernetes Events."""

from datetime import datetime

from sqlalchemy import Column, DateTime, UniqueConstraint, text
from sqlmodel import Field, Index, SQLModel


class K8sEvent(SQLModel, table=True):
    """Repräsentiert ein Kubernetes Event in der Datenbank."""

    # Automatischer Primärschlüssel
    id: int | None = Field(default=None, primary_key=True)

    # Eindeutige ID von Kubernetes
    uid: str = Field(index=True)

    # Der Name des Event-Objekts
    name: str = Field(index=True)

    # Namespace
    namespace: str = Field(index=True)

    # Grund des Events
    reason: str | None = Field(default=None, index=True)

    # Typ (Normal/Warning)
    type: str | None = Field(default=None, index=True)

    # Die ausführliche Beschreibung
    message: str | None = Field(default=None)

    # Welches Objekt betroffen ist
    involved_kind: str | None = Field(default=None, index=True)

    # Name des betroffenen Objekts
    involved_name: str | None = Field(default=None, index=True)

    # Reporting Component (kubelet, scheduler, etc.)
    component: str | None = Field(default=None, index=True)

    # Source Host/Node
    host: str | None = Field(default=None, index=True)

    # Zeitpunkte von Kubernetes
    first_timestamp: datetime | None = Field(default=None, index=True)
    last_timestamp: datetime | None = Field(default=None, index=True)

    # Wie oft dieses Event aggregiert wurde
    count: int | None = Field(default=1, index=True)

    # Zeitpunkt der Erfassung in unserer DB
    created_at: datetime | None = Field(
        default=None,
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            index=True,
            server_default=text('CURRENT_TIMESTAMP')
        )
    )

    # Composite Index für performante Dubletten-Prüfung
    __table_args__ = (
        Index("ix_k8sevent_uid_count", "uid", "count"),
        UniqueConstraint("uid", "count", name="uc_uid_count"),
    )
