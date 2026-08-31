import os


def enabled() -> bool:
    return bool(os.environ.get(_TRACE_DIR_ENV))


_TRACE_DIR_ENV = "IRIS_CANDIDATE_TRACE_DIR"
