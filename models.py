# models.py
from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel, Field

class K8sEvent(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    uid: str = Field(index=True)
    name: str = Field(index=True)
    namespace: str = Field(index=True)
    reason: Optional[str] = Field(default=None, index=True)
    type: Optional[str] = Field(default=None, index=True)
    message: Optional[str] = Field(default=None)
    involved_kind: Optional[str] = Field(default=None, index=True)
    involved_name: Optional[str] = Field(default=None, index=True)
    first_timestamp: Optional[datetime] = Field(default=None, index=True)
    last_timestamp: Optional[datetime] = Field(default=None, index=True)
    count: Optional[int] = Field(default=1)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
