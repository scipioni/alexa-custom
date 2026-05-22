"""Load .env from the current working directory (does not override existing env vars)."""

import os


def load_env():
    env_file = os.path.join(os.getcwd(), ".env")
    try:
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip()
                if key and value and key not in os.environ:
                    os.environ[key] = value
    except FileNotFoundError:
        pass


def require_env(key: str) -> str:
    value = os.environ.get(key, "").strip()
    if not value:
        raise RuntimeError(f"{key} is not set — fill it in .env")
    return value
