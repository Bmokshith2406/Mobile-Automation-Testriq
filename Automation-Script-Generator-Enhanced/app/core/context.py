import contextvars

active_framework_ctx = contextvars.ContextVar("active_framework_ctx", default=None)
