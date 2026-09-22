import importlib
import signal
from datetime import datetime

from bd_shared.logging_setup import configure_logging, get_logger


logger = get_logger(__name__)


def _parse_start_time(value):
    try:
        hour, minute = map(int, value.split(":"))
    except ValueError as exc:
        raise ValueError(
            f"Invalid start_time: {value!r}. Expected HH:MM format."
        ) from exc
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(
            f"Invalid start_time: {value!r}. Expected hour 00-23 and minute 00-59."
        )
    return hour, minute


if __name__ == "__main__":
    from bd_shared.config import LOG_LEVEL, SQLALCHEMY_LOGGING

    configure_logging(
        "webreport-data-collector",
        level=LOG_LEVEL,
        logger_levels={"sqlalchemy.engine": LOG_LEVEL}
        if SQLALCHEMY_LOGGING
        else None,
    )

    ZoneInfo = __import__("zoneinfo").ZoneInfo
    apscheduler_events = importlib.import_module("apscheduler.events")
    apscheduler_blocking = importlib.import_module("apscheduler.schedulers.blocking")
    apscheduler_interval = importlib.import_module("apscheduler.triggers.interval")
    bd_config = importlib.import_module("bd_shared.config")
    run_fetch = importlib.import_module("fetch_pipeline").run_fetch

    EVENT_JOB_ERROR = apscheduler_events.EVENT_JOB_ERROR
    EVENT_JOB_EXECUTED = apscheduler_events.EVENT_JOB_EXECUTED
    BlockingScheduler = apscheduler_blocking.BlockingScheduler
    IntervalTrigger = apscheduler_interval.IntervalTrigger
    XLSM_FETCH_INTERVAL_HOURS = bd_config.XLSM_FETCH_INTERVAL_HOURS
    XLSM_FETCH_START_TIME = bd_config.XLSM_FETCH_START_TIME
    XLSM_FETCH_TIMEZONE = bd_config.XLSM_FETCH_TIMEZONE

    hour, minute = _parse_start_time(XLSM_FETCH_START_TIME)

    if XLSM_FETCH_INTERVAL_HOURS <= 0:
        raise ValueError(
            f"interval_hours must be > 0, got {XLSM_FETCH_INTERVAL_HOURS}"
        )

    try:
        tz = ZoneInfo(XLSM_FETCH_TIMEZONE)
    except Exception as exc:
        raise ValueError(f"Invalid timezone: {XLSM_FETCH_TIMEZONE!r}") from exc

    scheduler = BlockingScheduler(timezone=tz)

    def job_executed_listener(event):
        logger.info("scheduler_job_executed", scheduler_job_id=event.job_id)

    def job_error_listener(event):
        if event.traceback is not None and not isinstance(event.traceback, str):
            logger.error(
                "scheduler_job_failed",
                scheduler_job_id=event.job_id,
                exc_info=(type(event.exception), event.exception, event.traceback),
            )
        else:
            logger.error(
                "scheduler_job_failed",
                scheduler_job_id=event.job_id,
                traceback=event.traceback,
                exc_info=False,
            )

    scheduler.add_listener(job_executed_listener, EVENT_JOB_EXECUTED)
    scheduler.add_listener(job_error_listener, EVENT_JOB_ERROR)

    start_date = datetime.now(tz=tz).replace(
        hour=hour, minute=minute, second=0, microsecond=0
    )

    scheduler.add_job(
        run_fetch,
        trigger=IntervalTrigger(
            hours=XLSM_FETCH_INTERVAL_HOURS,
            start_date=start_date,
            timezone=tz,
        ),
        id="xlsm_fetch",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=60,
    )

    signal.signal(signal.SIGTERM, lambda sig, frame: scheduler.shutdown(wait=True))
    signal.signal(signal.SIGINT, lambda sig, frame: scheduler.shutdown(wait=True))

    logger.info(
        "scheduler_starting",
        next_fetch_at=start_date.isoformat(),
        interval_hours=XLSM_FETCH_INTERVAL_HOURS,
    )

    try:
        scheduler.start()
    except KeyboardInterrupt:
        scheduler.shutdown(wait=True)
