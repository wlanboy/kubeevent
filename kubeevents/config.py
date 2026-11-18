"""Konfiguration aus Umgebungsvariablen und der Datei .env."""

from functools import cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Alle Einstellungen des Dienstes. Umgebungsvariablen haben Vorrang vor der Datei .env."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Pfad zur SQLite-Datei, das Verzeichnis wird bei Bedarf angelegt
    db_path: str = "data/events.db"

    # Kommagetrennte Liste der beobachteten Namespaces
    watch_namespaces: str = ""
    # Früherer Name von WATCH_NAMESPACES, gilt nur, wenn WATCH_NAMESPACES leer ist
    pod_namespace: str = ""

    # Events, die älter sind, löscht der Retention-Job
    retention_days: int = Field(default=7, ge=1)
    # Metrik-Zeitreihen ohne neues Event in diesem Zeitraum werden aus /metrics entfernt
    metrics_series_ttl_hours: int = Field(default=24, ge=1)

    # Puffer zwischen Watchern und DB-Worker
    queue_maxsize: int = Field(default=10000, ge=1)
    # Größe und maximale Wartezeit eines Batches im DB-Worker
    batch_max_size: int = Field(default=500, ge=1, le=2000)
    batch_max_delay: float = Field(default=0.2, gt=0)

    # Nach dieser Zeit beendet der API-Server einen Watch, der Watcher verbindet sich neu
    watch_timeout_seconds: int = Field(default=300, ge=10)

    log_level: str = "INFO"

    # Nur für den Start über main.py
    host: str = "0.0.0.0"
    port: int = 8001
    reload: bool = False

    @property
    def namespaces(self) -> list[str]:
        raw = self.watch_namespaces or self.pod_namespace or "demo"
        return [ns.strip() for ns in raw.split(",") if ns.strip()]


@cache
def get_settings() -> Settings:
    return Settings()
