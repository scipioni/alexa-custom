import os


def require_env(key: str) -> str:
    value = os.environ.get(key, "").strip()
    if not value:
        raise RuntimeError(f"{key} is not set — add it to config.yaml under env:")
    return value
