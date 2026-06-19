import contextvars

_token_bucket = contextvars.ContextVar("token_bucket", default=None)


def _bucket() -> dict:
    bucket = _token_bucket.get()
    if bucket is None:
        bucket = {"input": 0, "output": 0}
        _token_bucket.set(bucket)
    return bucket

def reset_tokens():
    _token_bucket.set({"input": 0, "output": 0})

def add_input_tokens(n: int):
    if isinstance(n, int) and n > 0:
        _bucket()["input"] += n

def add_output_tokens(n: int):
    if isinstance(n, int) and n > 0:
        _bucket()["output"] += n

def get_input_tokens() -> int:
    return _bucket()["input"]

def get_output_tokens() -> int:
    return _bucket()["output"]

def get_total_tokens() -> int:
    bucket = _bucket()
    return bucket["input"] + bucket["output"]

def get_token_stats() -> dict:
    return {
        "input_tokens": get_input_tokens(),
        "output_tokens": get_output_tokens(),
        "total_tokens": get_total_tokens(),
    }

