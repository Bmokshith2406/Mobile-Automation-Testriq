import logging
from app.main import PrettyFormatter, ExtraFieldsFilter


def test_pretty_formatter_info():
    formatter = PrettyFormatter()
    record = logging.LogRecord(
        name="app",
        level=logging.INFO,
        pathname="test.py",
        lineno=10,
        msg="Application started version=%s",
        args=("3.0.0",),
        exc_info=None
    )
    
    filt = ExtraFieldsFilter()
    filt.filter(record)
    
    formatted = formatter.format(record)
    assert "✨" in formatted
    assert "INFO" in formatted
    assert "app" in formatted
    assert "Application started version=3.0.0" in formatted


def test_pretty_formatter_error():
    formatter = PrettyFormatter()
    record = logging.LogRecord(
        name="llm",
        level=logging.ERROR,
        pathname="test.py",
        lineno=20,
        msg="Failed to query API",
        args=(),
        exc_info=None
    )
    
    filt = ExtraFieldsFilter()
    filt.filter(record)
    
    formatted = formatter.format(record)
    assert "❌" in formatted
    assert "ERROR" in formatted
    assert "llm" in formatted
    assert "Failed to query API" in formatted


def test_pretty_formatter_access_log():
    formatter = PrettyFormatter()
    record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname="test.py",
        lineno=30,
        msg='%s - "%s %s HTTP/%s" %d',
        args=("127.0.0.1:54321", "GET", "/health", "1.1", 200),
        exc_info=None
    )
    
    filt = ExtraFieldsFilter()
    filt.filter(record)
    
    formatted = formatter.format(record)
    assert "🌐" in formatted
    assert "GET" in formatted
    assert "/health" in formatted
    assert "200" in formatted
