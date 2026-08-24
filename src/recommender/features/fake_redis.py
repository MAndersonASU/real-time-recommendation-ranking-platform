class InMemoryRedis:
    """A minimal, in-process stand-in for the one Redis surface this
    project's state-store code actually calls (`get`, `set`, `ping`) --
    real isolation for anything that must never depend on ambient,
    shared Redis contents (an evaluation run, a test), without needing a
    real Redis connection at all. Each instance starts empty and is
    never shared implicitly; a caller that wants a clean run creates a
    new one.
    """

    def __init__(self) -> None:
        self._data: dict[str, str] = {}

    def set(self, key: str, value: str, ex: int | None = None) -> None:
        self._data[key] = value

    def get(self, key: str) -> str | None:
        return self._data.get(key)

    def ping(self) -> bool:
        return True
