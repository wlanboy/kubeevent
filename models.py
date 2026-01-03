from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel, Field, Index
from sqlalchemy import Column, DateTime, text

class K8sEvent(SQLModel, table=True):
    # Automatischer Primärschlüssel
    id: Optional[int] = Field(default=None, primary_key=True)
    
    # Eindeutige ID von Kubernetes
    uid: str = Field(index=True)
    
    # Der Name des Event-Objekts
    name: str = Field(index=True)
    
    # Namespace
    namespace: str = Field(index=True)
    
    # Grund des Events
    reason: Optional[str] = Field(default=None, index=True)
    
    # Typ (Normal/Warning)
    type: Optional[str] = Field(default=None, index=True)
    
    # Die ausführliche Beschreibung
    message: Optional[str] = Field(default=None)
    
    # Welches Objekt betroffen ist
    involved_kind: Optional[str] = Field(default=None, index=True)
    
    # Name des betroffenen Objekts
    involved_name: Optional[str] = Field(default=None, index=True)
    
    # Zeitpunkte von Kubernetes
    first_timestamp: Optional[datetime] = Field(default=None, index=True)
    last_timestamp: Optional[datetime] = Field(default=None, index=True)
    
    # Wie oft dieses Event aggregiert wurde
    count: Optional[int] = Field(default=1, index=True)
    
    # Korrektur für created_at:
    # Wir verschieben den Index-Parameter IN die Column-Definition.
    created_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True), 
            index=True,  # Hier wird der Index jetzt definiert
            server_default=text('CURRENT_TIMESTAMP')
        )
    )

    # Composite Index für performante Dubletten-Prüfung
    __table_args__ = (
        Index("ix_k8sevent_uid_count", "uid", "count"),
    )