"""Local Superset 3.0 SQL alert delivery. No secrets in this file."""
import os
from pathlib import Path
from celery.schedules import crontab

SECRET_KEY = os.environ.get("SUPERSET_SECRET_KEY") or Path(
    "/app/superset_home/.assetpulse_secret_key"
).read_text()
FEATURE_FLAGS = {"ALERT_REPORTS": True, "ALERTS_ATTACH_REPORTS": False}
ALERT_REPORTS_NOTIFICATION_DRY_RUN = False
SMTP_HOST = "assetpulse-mailpit"
SMTP_PORT = 1025
SMTP_STARTTLS = False
SMTP_SSL = False
SMTP_USER = None
SMTP_PASSWORD = None
SMTP_MAIL_FROM = "assetpulse@local.test"
WEBDRIVER_BASEURL = "http://assetpulse-superset:8088/"
WEBDRIVER_BASEURL_USER_FRIENDLY = "http://localhost:8089/"
# Preserve the existing SQLite metadata for this single-worker local test.
SQLALCHEMY_ENGINE_OPTIONS = {"connect_args": {"timeout": 30}}

class CeleryConfig:
    broker_url = "redis://assetpulse-alert-redis:6379/0"
    result_backend = "redis://assetpulse-alert-redis:6379/1"
    imports = ("superset.sql_lab", "superset.tasks.scheduler")
    worker_prefetch_multiplier = 1
    task_acks_late = True
    timezone = "UTC"
    beat_schedule = {
        "reports.scheduler": {"task": "reports.scheduler", "schedule": crontab(minute="*")},
        "reports.prune_log": {"task": "reports.prune_log", "schedule": crontab(minute=0, hour=0)},
    }

CELERY_CONFIG = CeleryConfig

def normalize_scheduled_time(value):
    """Celery 5 serializes ETA as ISO text; SQLite DateTime rejects text."""
    from datetime import datetime, timezone
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value is not None and value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value

def configure_local_sqlite_compatibility(app):
    if not app.config["SQLALCHEMY_DATABASE_URI"].startswith("sqlite:"):
        return
    from sqlalchemy import event
    from superset.reports.models import ReportExecutionLog
    def convert_eta(mapper, connection, target):
        target.scheduled_dttm = normalize_scheduled_time(target.scheduled_dttm)
    event.listen(ReportExecutionLog, "before_insert", convert_eta)

FLASK_APP_MUTATOR = configure_local_sqlite_compatibility
