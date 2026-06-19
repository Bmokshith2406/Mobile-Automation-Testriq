from __future__ import annotations

import ast
import re
from typing import List, Set, Tuple


class ASTSecurityVisitor(ast.NodeVisitor):
    """
    AST Visitor to inspect Python scripts for security violations.
    """

    def __init__(
        self,
        forbidden_imports: Set[str],
        allowed_imports: Set[str],
        forbidden_calls: Set[str],
        forbidden_attrs: Set[str],
        strict_mode: bool,
    ):
        self.forbidden_imports = forbidden_imports
        self.allowed_imports = allowed_imports
        self.forbidden_calls = forbidden_calls
        self.forbidden_attrs = forbidden_attrs
        self.strict_mode = strict_mode
        self.errors: List[str] = []

    def visit_Import(self, node: ast.Import):
        for name in node.names:
            base_module = name.name.split(".")[0]
            if base_module in self.forbidden_imports:
                self.errors.append(f"Forbidden import: {name.name}")
            elif self.strict_mode and base_module not in self.allowed_imports:
                self.errors.append(f"Disallowed import in strict mode: {name.name}")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        if node.module:
            base_module = node.module.split(".")[0]
            if base_module in self.forbidden_imports:
                self.errors.append(f"Forbidden import: {node.module}")
            elif self.strict_mode and base_module not in self.allowed_imports:
                self.errors.append(f"Disallowed import in strict mode: {node.module}")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call):
        # 1. Direct call checks
        if isinstance(node.func, ast.Name):
            func_name = node.func.id
            if func_name in self.forbidden_calls:
                self.errors.append(f"Forbidden function call: {func_name}")

            # Safe-guard getattr/setattr/delattr calls
            if func_name in {"getattr", "setattr", "delattr"} and len(node.args) >= 2:
                second_arg = node.args[1]
                if isinstance(second_arg, ast.Constant) and isinstance(second_arg.value, str):
                    val = second_arg.value
                    if val.startswith("__") or val in {"subclasses", "mro"} or val in self.forbidden_calls:
                        self.errors.append(f"Forbidden dynamic access of: {val}")
                else:
                    self.errors.append("Dynamic non-constant attribute resolution is blocked")

        # 2. Method/Attribute call checks (e.g. os.listdir)
        elif isinstance(node.func, ast.Attribute):
            if node.func.attr in self.forbidden_calls or node.func.attr in self.forbidden_attrs:
                self.errors.append(f"Forbidden method/function call: {node.func.attr}")

        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute):
        # Block access to magic/internal attributes
        attr = node.attr
        if (
            (attr.startswith("__") and attr != "__name__")
            or attr in {"subclasses", "mro"}
            or attr in self.forbidden_attrs
        ):
            self.errors.append(f"Forbidden access to internal attribute: {attr}")
        self.generic_visit(node)


class ScriptSecurityValidator:
    """
    Validates Python scripts for security before execution.

    Blocks dangerous operations that could compromise the system.
    """

    FORBIDDEN_IMPORTS: Set[str] = {
        "subprocess",
        "shutil",
        "ctypes",
        "multiprocessing",
        "signal",
        "socket",
        "http.server",
        "ftplib",
        "smtplib",
        "telnetlib",
        "pickle",
        "marshal",
        "shelve",
        "code",
        "codeop",
        "pty",
        "tty",
        "fcntl",
        "resource",
        "sysconfig",
        "gc",
        "importlib",
    }

    FORBIDDEN_CALLS: Set[str] = {
        "eval",
        "exec",
        "compile",
        "__import__",
        "memoryview",
        "listdir",
    }

    FORBIDDEN_ATTRS: Set[str] = {
        "system",
        "popen",
        "spawn",
        "spawnl",
        "spawnle",
        "spawnlp",
        "spawnlpe",
        "spawnv",
        "spawnve",
        "spawnvp",
        "spawnvpe",
        "Popen",
        "call",
        "check_call",
        "check_output",
        "modules",
        "rmtree",
        "remove",
        "unlink",
        "rename",
        "rmdir",
        "scandir",
        "kill",
        "fork",
        "forkpty",
        "startfile",
        "execl",
        "execle",
        "execlp",
        "execlpe",
        "execv",
        "execve",
        "execvp",
        "execvpe",
        "read_text",
        "read_bytes",
        "glob",
        "rglob",
        "iterdir",
        "resolve",
        "absolute",
        "chmod",
        "chown",
    }

    ALLOWED_IMPORTS: Set[str] = {
        "playwright",
        "cv2",
        "mss",
        "numpy",
        "threading",
        "playwright.sync_api",
        "playwright.async_api",
        "selenium",
        "appium",
        "asyncio",
        "re",
        "base64",
        "json",
        "time",
        "datetime",
        "typing",
        "dataclasses",
        "enum",
        "functools",
        "itertools",
        "collections",
        "math",
        "random",
        "string",
        "uuid",
        "os",
        "pathlib",
        "logging",
        "traceback",
        "inspect",
        "sys",
        "hashlib",
    }

    DANGEROUS_PATTERNS: List[re.Pattern] = [
        re.compile(r"\.mro\s*\("),
        re.compile(r"\.subclasses\s*\("),
        re.compile(r"breakpoint\s*\("),
    ]

    def __init__(self, strict_mode: bool = False):
        self.strict_mode = strict_mode

    def validate(self, script_content: str) -> Tuple[bool, str]:
        # 1. AST-based structural security visitor checks
        try:
            tree = ast.parse(script_content)
            visitor = ASTSecurityVisitor(
                forbidden_imports=self.FORBIDDEN_IMPORTS,
                allowed_imports=self.ALLOWED_IMPORTS,
                forbidden_calls=self.FORBIDDEN_CALLS,
                forbidden_attrs=self.FORBIDDEN_ATTRS,
                strict_mode=self.strict_mode,
            )
            visitor.visit(tree)
            if visitor.errors:
                return False, visitor.errors[0]
        except SyntaxError as e:
            return False, f"Syntax Error: {e}"
        except Exception as e:
            return False, f"Security analysis failed: {e}"

        # 2. Regex-based defense-in-depth safety checks
        import_pattern = re.compile(r"(?:from\s+(\S+)\s+import|import\s+(\S+))")

        for match in import_pattern.finditer(script_content):
            module = match.group(1) or match.group(2)
            base_module = module.split(".")[0]

            if base_module in self.FORBIDDEN_IMPORTS:
                return False, f"Forbidden import: {module}"

            if self.strict_mode:
                if base_module not in self.ALLOWED_IMPORTS:
                    if not any(module.startswith(allowed + ".") for allowed in self.ALLOWED_IMPORTS):
                        return False, f"Disallowed import in strict mode: {module}"

        for func in self.FORBIDDEN_CALLS:
            pattern = re.compile(rf"\b{func}\s*\(")
            if pattern.search(script_content):
                return False, f"Forbidden function call: {func}"

        for attr in self.FORBIDDEN_ATTRS:
            pattern = re.compile(rf"\.\s*{attr}\s*\(")
            if pattern.search(script_content):
                return False, f"Forbidden method/function call: {attr}"

        for pattern in self.DANGEROUS_PATTERNS:
            if pattern.search(script_content):
                return False, f"Dangerous pattern detected: {pattern.pattern}"

        return True, ""

    def contains_forbidden_pattern(self, code: str) -> bool:
        is_valid, _ = self.validate(code)
        return not is_valid
