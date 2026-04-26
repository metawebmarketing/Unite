from django.core.cache import cache


def _version_key(user_id: int) -> str:
    return f"feed:user-version:{int(user_id)}"


def get_user_feed_cache_version(user_id: int) -> int:
    key = _version_key(user_id)
    value = cache.get(key)
    if isinstance(value, int) and value > 0:
        return value
    cache.set(key, 1, timeout=None)
    return 1


def bump_user_feed_cache_version(user_id: int) -> int:
    key = _version_key(user_id)
    try:
        value = cache.incr(key)
        if isinstance(value, int) and value > 0:
            return value
    except ValueError:
        # Key does not exist for some backends (e.g., locmem after restart).
        pass
    cache.set(key, 2, timeout=None)
    return 2
