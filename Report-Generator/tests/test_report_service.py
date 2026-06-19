import io
from dataclasses import dataclass
from typing import BinaryIO

from app.services.report_service import ReportService
from app.services.zip_service import ZipService


@dataclass
class MockUploadFile:
    file: BinaryIO
    filename: str = "malicious.zip"
    content_type: str = "application/zip"
    size: int = 1000


def test_report_service_escapes_html_and_sanitizes_urls(malicious_zip_bytes: bytes):
    zip_service = ZipService()
    report_service = ReportService()

    report_data = zip_service.extract_and_parse(MockUploadFile(file=io.BytesIO(malicious_zip_bytes)))
    html = report_service.generate_html(report_data)

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "javascript:alert(3)" not in html
    assert "&lt;img src=x onerror=alert(1)&gt;" in html


def test_report_service_normalizes_double_spaced_scripts():
    report_service = ReportService()

    # Case 1: Normal script should be unmodified
    normal_script = "import re\nimport sys\n\n\ndef foo():\n    pass\n"
    assert report_service._normalize_script_spacing(normal_script) == normal_script

    # Case 2: Double-spaced script (even-indexed lines empty) should be collapsed
    double_spaced_even = "import re\n\nimport sys\n\n\n\n\n\ndef foo():\n\n    pass\n\n"
    expected_collapsed = "import re\nimport sys\n\n\ndef foo():\n    pass\n"
    assert report_service._normalize_script_spacing(double_spaced_even) == expected_collapsed

    # Case 3: Double-spaced script (odd-indexed lines empty) should be collapsed
    double_spaced_odd = "\nimport re\n\nimport sys\n\n\n\n\n\ndef foo():\n\n    pass\n"
    expected_collapsed_odd = "import re\nimport sys\n\n\ndef foo():\n    pass\n"
    assert report_service._normalize_script_spacing(double_spaced_odd) == expected_collapsed_odd
