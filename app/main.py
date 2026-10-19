"""Application entry point: python -m app.main."""

import logging
import os
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from zoneinfo import ZoneInfo


def main():
    from waitress import serve

    from .service import UpdaterService
    from .web import create_app

    data_dir = Path(os.environ.get("DATA_DIR", "/app/data"))
    data_dir.mkdir(parents=True, exist_ok=True)
    timezone = os.environ.get("TZ", "Asia/Shanghai")

    class TimezoneFormatter(logging.Formatter):
        def formatTime(self, record, datefmt=None):
            return datetime.fromtimestamp(record.created, ZoneInfo(timezone)).isoformat(
                timespec="seconds"
            )

    file_handler = RotatingFileHandler(
        data_dir / "updater.log", maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    formatter = TimezoneFormatter("%(asctime)s %(levelname)s %(message)s")
    handlers = [file_handler, logging.StreamHandler()]
    for handler in handlers:
        handler.setFormatter(formatter)
    logging.basicConfig(level=logging.INFO, handlers=handlers)
    service = UpdaterService(data_dir, timezone=timezone)
    app = create_app(service)
    service.start()
    try:
        serve(
            app,
            host=os.environ.get("WEB_HOST", "0.0.0.0"),
            port=int(os.environ.get("WEB_PORT", "8080")),
            threads=8,
        )
    finally:
        service.stop()


if __name__ == "__main__":
    main()
