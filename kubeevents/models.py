"""Tabelle für Kubernetes Events."""

from datetime import datetime

from sqlalchemy import Column, DateTime, Index, UniqueConstraint, text
from sqlmodel import Field, SQLModel


class K8sEvent(SQLModel, table=True):
    """Ein Kubernetes Event. Jede Kombination aus uid und count wird einmal gespeichert."""

    __table_args__ = (
        # Der Unique-Index deckt auch Abfragen auf uid allein ab
        UniqueConstraint("uid", "count", name="uc_uid_count"),
        # Zeitfenster in /events/stats, Sortierung nach Eingang und Retention
        Index("ix_k8sevent_created_at_type", "created_at", "type"),
    )

    id: int | None = Field(default=None, primary_key=True)

    # Eindeutige ID des Event-Objekts in Kubernetes
    uid: str
    name: str
    namespace: str = Field(index=True)

    reason: str | None = None
    # Normal oder Warning
    type: str | None = Field(default=None, index=True)
    message: str | None = None

    # Das Objekt, auf das sich das Event bezieht
    involved_kind: str | None = Field(default=None, index=True)
    involved_name: str | None = None

    # Meldende Komponente (kubelet, scheduler, ...) und Node
    component: str | None = None
    host: str | None = None

    first_timestamp: datetime | None = None
    last_timestamp: datetime | None = None

    # Wie oft Kubernetes dieses Event zusammengefasst hat
    count: int = 1

    # Zeitpunkt der Speicherung in dieser Datenbank, naive UTC
    created_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    )
