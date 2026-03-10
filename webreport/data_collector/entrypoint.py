__import__("sys").path.insert(0, "/")

import logging
import signal
from datetime import datetime
import importlib


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
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

    try:
        hour, minute = map(int, XLSM_FETCH_START_TIME.split(":"))
        assert 0 <= hour <= 23 and 0 <= minute <= 59
    except (ValueError, AssertionError) as exc:
        raise ValueError(
            f"Invalid start_time: {XLSM_FETCH_START_TIME!r}. Expected HH:MM format."
        ) from exc

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
        logging.info("Job executed successfully at %s", datetime.now(tz=tz))

    def job_error_listener(event):
        logging.error("Job failed: %s", event.exception)

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

    logging.info(
        "Scheduler starting. Next fetch at ~%s, interval=%sh",
        start_date,
        XLSM_FETCH_INTERVAL_HOURS,
    )

    try:
        scheduler.start()
    except KeyboardInterrupt:
        scheduler.shutdown(wait=True)
