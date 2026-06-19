import time
from functools import wraps
from itertools import chain
from typing import Any, Callable, Iterable, List


def measure_time(func: Callable) -> Callable:
    """
    Measure execution time of a function in milliseconds.

    Used for performance monitoring inside the
    Playwright Python Method Extraction pipeline.
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        result = func(*args, **kwargs)
        wrapper.last_duration_ms = round(
            (time.perf_counter() - start) * 1000, 2
        )
        return result

    wrapper.last_duration_ms = None
    return wrapper


def safe_decode(raw_bytes: bytes) -> str:
    """
    Safely decode raw bytes into text.

    This is useful when reading uploaded Playwright
    Python scripts that may contain mixed encodings.
    """
    try:
        return raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return raw_bytes.decode("latin-1")


def flatten(list_of_lists: Iterable[Iterable[Any]]) -> List[Any]:
    """
    Flatten a nested iterable into a single list.
    """
    return list(chain.from_iterable(list_of_lists))
