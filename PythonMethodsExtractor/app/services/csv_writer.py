import csv
import io
from typing import Iterable, List

from app.services.scanner import MethodInfo


def prevent_excel_injection(text: str) -> str:
    """
    Prevent CSV/Excel formula injection.

    Any line starting with =, +, -, or @ is prefixed
    with a single quote to ensure safe rendering.
    """
    stripped = text.lstrip()
    if stripped.startswith(("=", "+", "-", "@")):
        return "'" + text
    return text


def method_to_string(m: MethodInfo) -> str:
    parts: List[str] = []

    if m.injected_vars:
        for line in m.injected_vars:
            normalized = line.replace("\r\n", "\n").replace("\r", "\n")
            parts.append(normalized)
        parts.append("")

    method_code = m.code.replace("\r\n", "\n").replace("\r", "\n")
    parts.append(method_code)

    final_block = "\n".join(parts).rstrip()

    safe_lines = [
        prevent_excel_injection(line)
        for line in final_block.split("\n")
    ]

    return "\n".join(safe_lines)


def write_methods_to_csv(methods: List[MethodInfo]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output, quoting=csv.QUOTE_ALL)

    writer.writerow(["Raw Method"])

    for m in methods:
        writer.writerow([method_to_string(m)])

    return output.getvalue().encode("utf-8")


def iter_csv_rows(methods: List[MethodInfo]) -> Iterable[str]:
    output = io.StringIO(newline="")
    writer = csv.writer(output, quoting=csv.QUOTE_ALL)
    writer.writerow(["Raw Method"])
    yield output.getvalue()

    for m in methods:
        output = io.StringIO(newline="")
        writer = csv.writer(output, quoting=csv.QUOTE_ALL)
        writer.writerow([method_to_string(m)])
        yield output.getvalue()
