"""Entrypoint shared by both run modes. `python -m onvif_sua` and the `onvif-sua`
console script both call `main()`, so there is no duplicated boot logic."""
import asyncio
import threading

from . import config
from . import mqtt
from . import worker


def _run_web():
    import uvicorn
    # `onvif_sua.web` re-exports the FastAPI instance as `app`, so import it directly.
    from .web import app as fastapi_app
    uvicorn.run(fastapi_app, host="0.0.0.0", port=config.WEB_PORT, log_level="warning")


def main():
    config._load_settings_yaml()   # unico store runtime (MQTT, scan, password web)
    # Expose the (possibly reloaded) cache-busting token to the template env.
    from .web.app import templates
    templates.env.globals["asset_version"] = config._cfg.get("asset_version", "1")
    worker._load_alarm_file()
    mqtt._mqtt_init()
    threading.Thread(target=_run_web, daemon=True, name="web").start()
    threading.Thread(target=worker._save_loop, daemon=True, name="saver").start()
    # _main_loop_coro installs the SIGTERM/SIGINT graceful-shutdown handlers and
    # keeps the event loop (and the daemon web/save threads) alive.
    asyncio.run(worker._main_loop_coro())


if __name__ == "__main__":
    main()
