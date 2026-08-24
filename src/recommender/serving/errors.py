class DependencyUnavailableError(Exception):
    """A specific, external or in-process dependency (Redis, the Faiss
    index, the two-tower model) could not serve this request. Raised
    only at the exact call site where a known dependency's own library
    exception was caught and translated -- never a blanket stand-in for
    "any RuntimeError or OSError anywhere in the call stack." That
    narrowness is what lets `safe_recommend` degrade gracefully on a
    genuine dependency failure while still letting an unrelated
    programming bug (a real defect in feature construction, ranking, or
    reranking) reach the API's own error handler instead of being
    silently reported as a successful response.
    """

    def __init__(self, reason: str, *args: object) -> None:
        super().__init__(reason, *args)
        self.reason = reason
