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

    def set(self, key: str, value: str, ex: int | None = None, nx: bool = False) -> bool | None:
        """`nx=True` sets only when the key is absent and reports whether
        it did, matching Redis's own SET NX. `claim_event`
        (`recommender.features.state_store`) relies on that single
        operation being the atomic step deciding whether an event has
        already been applied, so a stand-in that ignored `nx` would
        quietly break the guarantee it exists to provide.
        """
        if nx and key in self._data:
            return None
        self._data[key] = value
        return True

    def get(self, key: str) -> str | None:
        return self._data.get(key)

    def ping(self) -> bool:
        return True
