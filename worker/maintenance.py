import logging
from threading import Event, Thread

from api.app.config import get_settings
from api.app.dispatch import dispatch_pending, recover_tasks
from worker.pipeline.cleanup import cleanup_sources
from worker.pipeline.ytdlp import update_if_due

logger = logging.getLogger(__name__)


def start_maintenance(stop: Event) -> Thread:
    def loop():
        while not stop.is_set():
            try:
                recover_tasks()
                dispatch_pending()
            except Exception:
                logger.exception("Worker maintenance will retry on the next interval")
            stop.wait(get_settings().maintenance_interval_seconds)

    thread = Thread(target=loop, name="cuplik-maintenance", daemon=True)
    thread.start()

    def updates():
        while not stop.is_set():
            try:
                update_if_due()
            except Exception:
                logger.warning("yt-dlp update check will be retried")
            stop.wait(60)

    Thread(target=updates, name="cuplik-ytdlp-update", daemon=True).start()

    def cleanup():
        while not stop.is_set():
            try:
                removed = cleanup_sources()
                if removed:
                    logger.info("Expired %d unused source copies", len(removed))
            except Exception:
                logger.exception("Source cache cleanup will be retried")
            stop.wait(3600)

    Thread(target=cleanup, name="cuplik-source-cleanup", daemon=True).start()
    return thread
