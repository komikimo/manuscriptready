from celery import Celery
import os

broker = os.getenv("CELERY_BROKER_URL") or os.getenv("REDIS_URL", "redis://localhost:6379/0")
backend = os.getenv("CELERY_RESULT_BACKEND") or "redis://localhost:6379/1"

celery_app = Celery(
    "manuscriptready",
    broker=broker,
    backend=backend,
    include=["app.worker.tasks"],
)

celery_app.conf.update(
    task_track_started=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    broker_transport_options={"visibility_timeout": 3600},
)


# Run scheduled tasks in UTC (keep simple)
celery_app.conf.beat_schedule = {
    "purge-expired-documents-daily": {
        "task": "retention.purge_expired_documents",
        "schedule": 60 * 60 * 24,
    }
}
