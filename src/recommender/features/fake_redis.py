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
        *contract*: refuse an already-claimed event returning the current
        state, or claim the event and apply its delta to whatever state
        is current. This instance is single-threaded, so those steps are
        atomic by construction rather than by locking.

        Applying the delta here, rather than accepting a caller-supplied
        state, is the point: it is what removes the stale-basis lost
        update the previous design allowed.
        """
        import json as _json

        claim_key, state_key = args[0], args[1]
        user_id, event_type, item_id, event_time = args[2], args[3], args[4], args[5]
        max_history = int(args[6])

        if claim_key in self._data:
            return [0, self._data.get(state_key, "")]

        raw = self._data.get(state_key)
        state = None
        if raw:
            try:
                state = _json.loads(raw)
            except ValueError:
                state = None
        if not state:
            state = {
                "user_id": user_id, "recent_clicked_items": [],
                "impressions_seen": 0, "clicks_seen": 0, "last_event_time": None,
            }
        state.setdefault("recent_clicked_items", [])

        if event_type == "click":
            state["clicks_seen"] = int(state.get("clicks_seen") or 0) + 1
            state["recent_clicked_items"].append(item_id)
            del state["recent_clicked_items"][:-max_history or None]
        else:
            state["impressions_seen"] = int(state.get("impressions_seen") or 0) + 1
        state["last_event_time"] = event_time or None
        state["version"] = int(state.get("version") or 0) + 1

        encoded = _json.dumps(state)
        self._data[claim_key] = "1"
        self._data[state_key] = encoded
        return [1, encoded]
