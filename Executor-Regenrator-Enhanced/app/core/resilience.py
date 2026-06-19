from __future__ import annotations
import time
import random
from dataclasses import dataclass
from enum import Enum

@dataclass
class CircuitBreaker:
    failure_threshold: int = 5
    reset_timeout_sec: int = 60
    recovery_timeout: float = 60.0
    half_open_max: int = 1

    _failure_count: int = 0
    _opened_at: float | None = None

    def __post_init__(self):
        if self.recovery_timeout != 60.0:
            self.reset_timeout_sec = int(self.recovery_timeout)

    def is_open(self) -> bool:
        if self._opened_at is None:
            return False
        if (time.time() - self._opened_at) > self.reset_timeout_sec:
            self._failure_count = 0
            self._opened_at = None
            return False
        return True

    def allow(self) -> bool:
        return not self.is_open()

    def record_success(self):
        self._failure_count = 0
        self._opened_at = None

    def record_failure(self):
        self._failure_count += 1
        if self._failure_count >= self.failure_threshold:
            self._opened_at = time.time()


class BackoffPolicy:
    def __init__(
        self,
        base: float = 0.5,
        factor: float = 2.0,
        max_delay: float = 30.0,
        base_delay: float | None = None,
        exponential_base: float | None = None,
        jitter: bool = True,
    ):
        self.base = base_delay if base_delay is not None else base
        self.factor = exponential_base if exponential_base is not None else factor
        self.max_delay = max_delay
        self.jitter_enabled = jitter

    def compute(self, attempt: int) -> float:
        delay = min(self.base * (self.factor ** attempt), self.max_delay)
        if self.jitter_enabled:
            jitter = random.uniform(0, delay * 0.1)
            return delay + jitter
        return delay

    def get_delay(self, attempt: int) -> float:
        return self.compute(attempt)


class RepairOutcome(str, Enum):
    SUCCESS = "success"
    NOT_REPAIRABLE = "not_repairable"
    TEMPORARY = "temporary"
    TIMEOUT = "timeout"
    INVALID_PATCH = "invalid_patch"
    MODEL_ERROR = "model_error"
