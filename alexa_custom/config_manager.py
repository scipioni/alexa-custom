from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Callable

from alexa_custom.config import ActionsConfig, ConfigError, load_config

logger = logging.getLogger(__name__)


class ConfigManager:
    def __init__(self, config: ActionsConfig | None) -> None:
        self.config = config
        self._callbacks: list[Callable[[ActionsConfig], None]] = []
        self._watcher_task: asyncio.Task | None = None

    def register_reload_callback(self, fn: Callable[[ActionsConfig], None]) -> None:
        self._callbacks.append(fn)

    def _reload(self, path: str | Path) -> None:
        try:
            new_config = load_config(path)
        except (ConfigError, Exception) as e:
            logger.error("Config reload failed, keeping previous config: %s", e)
            return

        if new_config is None:
            logger.error(
                "Config reload returned None (file gone?), keeping previous config"
            )
            return

        self.config = new_config
        for cb in self._callbacks:
            try:
                cb(new_config)
            except Exception as e:
                logger.error("Reload callback %r raised: %s", cb, e)

    def _log_env_reload(self, env_keys: list[str]) -> None:
        if env_keys:
            logger.debug("Config reload applied env keys: %s", ", ".join(env_keys))

    def start_watcher(self, path: str | Path, interval: float = 2.0) -> None:
        p = Path(path)
        self._watcher_task = asyncio.get_event_loop().create_task(
            self._poll_loop(p, interval)
        )

    def stop_watcher(self) -> None:
        if self._watcher_task is not None:
            self._watcher_task.cancel()
            self._watcher_task = None

    async def _poll_loop(self, path: Path, interval: float) -> None:
        try:
            last_mtime = path.stat().st_mtime if path.exists() else None
        except OSError:
            last_mtime = None

        try:
            while True:
                await asyncio.sleep(interval)
                try:
                    mtime = path.stat().st_mtime if path.exists() else None
                except OSError:
                    mtime = None

                if mtime != last_mtime:
                    last_mtime = mtime
                    if mtime is not None:
                        logger.info("Config file changed, reloading: %s", path)
                        self._reload(path)
        except asyncio.CancelledError:
            pass
