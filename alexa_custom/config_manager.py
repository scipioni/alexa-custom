from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from collections.abc import Awaitable
from typing import Callable

from alexa_custom.config import ActionsConfig, ConfigError, load_config

logger = logging.getLogger(__name__)


class ConfigManager:
    def __init__(self, config: ActionsConfig | None) -> None:
        self.config = config
        self._callbacks: list[Callable[[ActionsConfig], None]] = []
        self._watcher_task: asyncio.Task | None = None
        self._on_config_error: Callable[[str], None] | None = None

    def register_reload_callback(self, fn: Callable[[ActionsConfig], None]) -> None:
        self._callbacks.append(fn)

    def set_error_callback(self, fn: Callable[[str], None] | None) -> None:
        self._on_config_error = fn

    def _reload(self, path: str | Path) -> None:
        try:
            new_config = load_config(path)
        except (ConfigError, Exception) as e:
            msg = str(e)
            logger.error("Config reload failed, keeping previous config: %s", msg)
            if self._on_config_error:
                try:
                    self._on_config_error(msg)
                except Exception as cb_err:
                    logger.debug("Error callback raised: %s", cb_err)
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

    def start_watcher(self, path: str | Path, interval: float | None = None) -> None:
        p = Path(path)
        if interval is not None:
            cfg_interval = interval
        elif self.config is not None:
            cfg_interval = float(self.config.system.config_poll_interval)
        else:
            cfg_interval = 2.0
        self._watcher_task = asyncio.get_running_loop().create_task(
            self._poll_loop(p, cfg_interval)
        )

    def stop_watcher(self) -> None:
        if self._watcher_task is not None:
            self._watcher_task.cancel()
            self._watcher_task = None

    def start_source_watcher(
        self,
        path: str | Path,
        interval: float = 1.5,
        on_restart: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        p = Path(path)
        asyncio.get_running_loop().create_task(
            self._source_poll_loop(p, interval, on_restart)
        )

    async def _source_poll_loop(
        self,
        path: Path,
        interval: float,
        on_restart: Callable[[], Awaitable[None]] | None,
    ) -> None:
        import os
        import sys

        def get_mtimes():
            mtimes = {}
            for root, _, files in os.walk(path):
                for f in files:
                    if f.endswith(".py"):
                        fpath = Path(root) / f
                        try:
                            mtimes[str(fpath)] = fpath.stat().st_mtime
                        except OSError:
                            pass
            return mtimes

        last_mtimes = await asyncio.to_thread(get_mtimes)
        try:
            while True:
                await asyncio.sleep(interval)
                mtimes = await asyncio.to_thread(get_mtimes)
                if mtimes != last_mtimes:
                    logger.info("Source code changed, restarting...")
                    if on_restart:
                        try:
                            await on_restart()
                        except Exception as e:
                            logger.error(
                                "Source watcher on_restart callback failed: %s", e
                            )
                    await asyncio.sleep(0.3)
                    os.execv(sys.executable, [sys.executable] + sys.argv)
                last_mtimes = mtimes
        except asyncio.CancelledError:
            pass

    async def _poll_loop(self, path: Path, interval: float) -> None:
        def _mtime(p: Path) -> float | None:
            try:
                return p.stat().st_mtime if p.exists() else None
            except OSError:
                return None

        def _dir_mtimes(d: Path) -> dict[str, float]:
            result: dict[str, float] = {}
            if not d.is_dir():
                return result
            for p in d.glob("*.yaml"):
                # Never watch secrets.yaml
                if p.name == "secrets.yaml":
                    continue
                try:
                    result[str(p)] = p.stat().st_mtime
                except OSError:
                    pass
            return result

        last_mtime = _mtime(path)
        user_path = path.parent / "user.yaml"
        last_user_mtime = _mtime(user_path)

        # Resolve actions directory from current config, fall back to default
        actions_dir = self._resolve_actions_dir(path)
        last_actions_mtimes = _dir_mtimes(actions_dir)

        try:
            while True:
                await asyncio.sleep(interval)

                # Re-resolve actions dir in case config changed it
                actions_dir = self._resolve_actions_dir(path)

                mtime = _mtime(path)
                user_mtime = _mtime(user_path)
                actions_mtimes = _dir_mtimes(actions_dir)

                config_changed = mtime != last_mtime
                user_changed = user_mtime != last_user_mtime
                actions_changed = actions_mtimes != last_actions_mtimes

                if config_changed or user_changed or actions_changed:
                    last_mtime = mtime
                    last_user_mtime = user_mtime
                    last_actions_mtimes = actions_mtimes
                    if mtime is not None:
                        if actions_changed and not config_changed and not user_changed:
                            logger.info("Action file changed, reloading config")
                        elif user_changed and not config_changed:
                            logger.info("user.yaml changed, reloading config")
                        else:
                            logger.info("Config file changed, reloading: %s", path)
                        self._reload(path)
        except asyncio.CancelledError:
            pass

    def _resolve_actions_dir(self, config_path: Path) -> Path:
        """Return the actions directory as an absolute Path."""
        if self.config is not None:
            d = Path(self.config.actions.dir)
        else:
            d = Path("conf/actions")
        if not d.is_absolute():
            d = config_path.parent.parent / d
        return d
