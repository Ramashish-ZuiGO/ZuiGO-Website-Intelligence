from celery import Celery

from worker_app.config import get_settings
from worker_app.logging_config import configure_logging

settings = get_settings()
configure_logging(settings.log_level)
redis_url = str(settings.redis_url)

celery_app = Celery("website_intelligence_worker", broker=redis_url, backend=redis_url)
celery_app.conf.update(
    include=[
        "worker_app.tasks.health",
        "worker_app.tasks.analysis",
        "worker_app.tasks.discovery",
        "worker_app.tasks.page_analysis",
        "worker_app.tasks.real_analysis",
        "worker_app.tasks.agent_platform",
        "worker_app.tasks.browser_uat_tier0",
    ],
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # Admission control for browser-heavy work. Analysis stages run as a strict
    # chain, so at most one task per run is active and this value is effectively
    # "max concurrent analyses on this host". A single host saturates (and
    # starves the API/Postgres) at roughly four concurrent browser-heavy runs,
    # so the default stays well below that and is raised per environment.
    worker_concurrency=settings.celery_worker_concurrency,
    # Long acks_late tasks must not be reserved by a busy worker: a prefetched
    # task sits unacked and idle until the worker frees a slot, and is stranded
    # for the full broker visibility timeout if that worker dies. One reserved
    # task per slot is the correct setting for this workload.
    worker_prefetch_multiplier=1,
    # Redis may still be starting when the worker boots; retry instead of
    # crash-looping. Set explicitly because the Celery default flips in 6.0.
    broker_connection_retry_on_startup=True,
    # Defence in depth, NOT the exclusivity guarantee. Raised above the longest
    # stage runtime so a still-running stage is not pointlessly redelivered;
    # exclusivity itself is enforced durably in Postgres by the stage-ownership
    # claim in tasks/real_analysis.py, which holds even if this were misset.
    # Never lower it: broker redelivery is not this product's recovery
    # mechanism -- stale detection (900s) plus an explicit resume is.
    broker_transport_options={
        "visibility_timeout": settings.celery_broker_visibility_timeout_seconds,
    },
)
