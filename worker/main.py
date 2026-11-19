import logging
from threading import Event

from rq.worker import SpawnWorker

from api.app.jobs import connection
from worker.maintenance import start_maintenance


def main():
    logging.basicConfig(level=logging.INFO)
    stop = Event()
    maintenance = start_maintenance(stop)
    try:
        SpawnWorker(["cuplik"], connection=connection()).work(with_scheduler=True)
    finally:
        stop.set()
        maintenance.join(timeout=2)


if __name__ == "__main__":
    main()
