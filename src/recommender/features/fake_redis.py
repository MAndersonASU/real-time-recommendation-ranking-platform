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

    def eval(self, script: str, numkeys: int, *args):
        """Implements the one script this project runs
        (`_CLAIM_AND_APPLY_LUA`) natively in Python.

        A stand-in cannot execute Lua, so it implements the same
        *contract* instead: refuse an already-claimed event returning the
        current state, reject a stale-version write, or claim and write
        together. This instance is single-threaded, so those steps are
        atomic by construction rather than by locking.

        Deliberately keyed to the real script's argument order, so a
        change to the script that this stand-in does not follow shows up
        as a test failure rather than a silent divergence.
        """
        import json as _json

        claim_key, state_key = args[0], args[1]
        new_state, expected_version = args[2], int(args[3])

        if claim_key in self._data:
            return [0, self._data.get(state_key, "")]

        current = self._data.get(state_key)
        current_version = 0
        if current:
            try:
                current_version = int(_json.loads(current).get("version", 0))
            except (ValueError, TypeError):
                current_version = 0

        if current_version != expected_version:
            return [2, current or ""]

        self._data[claim_key] = "1"
        self._data[state_key] = new_state
        return [1, new_state]
