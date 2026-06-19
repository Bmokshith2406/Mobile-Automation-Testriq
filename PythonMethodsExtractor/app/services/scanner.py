import ast
import re
import textwrap
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple


@dataclass
class MethodInfo:
    name: str
    start_line: int
    end_line: int
    code: str
    class_name: Optional[str]
    is_nested: bool
    injected_vars: List[str]


def _get_node_end_lineno(node: ast.AST) -> int:
    if hasattr(node, "end_lineno") and node.end_lineno:
        return node.end_lineno

    max_lineno = getattr(node, "lineno", 0)
    for child in ast.walk(node):
        child_end = getattr(child, "end_lineno", None)
        if child_end:
            max_lineno = max(max_lineno, child_end)
        elif hasattr(child, "lineno"):
            max_lineno = max(max_lineno, child.lineno)
    return max_lineno


def _slice_source_lines(source_lines: List[str], start_line: int, end_line: int) -> str:
    start = max(0, start_line - 1)
    end = min(len(source_lines), end_line)
    return "\n".join(source_lines[start:end])


def _slice_node_source(source_lines: List[str], node: ast.AST, dedent: bool = False) -> str:
    code = _slice_source_lines(
        source_lines,
        getattr(node, "lineno", 1),
        _get_node_end_lineno(node),
    )
    if dedent:
        code = textwrap.dedent(code)
    return code.rstrip()


def extract_init_assignments(
    source_lines: List[str],
    tree: ast.AST,
) -> Dict[str, List[str]]:
    init_map: Dict[str, List[str]] = {}

    for node in getattr(tree, "body", []):
        if not isinstance(node, ast.ClassDef):
            continue

        assignments: List[str] = []
        for item in node.body:
            if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) or item.name != "__init__":
                continue

            for stmt in item.body:
                if isinstance(stmt, ast.Assign):
                    if any(
                        isinstance(target, ast.Attribute)
                        and isinstance(target.value, ast.Name)
                        and target.value.id == "self"
                        for target in stmt.targets
                    ):
                        assignments.append(_slice_node_source(source_lines, stmt, dedent=True))
                elif isinstance(stmt, ast.AnnAssign):
                    target = stmt.target
                    if (
                        isinstance(target, ast.Attribute)
                        and isinstance(target.value, ast.Name)
                        and target.value.id == "self"
                    ):
                        assignments.append(_slice_node_source(source_lines, stmt, dedent=True))

        if assignments:
            init_map[node.name] = assignments

    return init_map


def extract_global_assignments(source_lines: List[str], tree: ast.AST) -> List[str]:
    global_blocks: List[str] = []

    for node in getattr(tree, "body", []):
        if isinstance(node, ast.Assign):
            if any(isinstance(target, ast.Name) for target in node.targets):
                global_blocks.append(_slice_node_source(source_lines, node))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            global_blocks.append(_slice_node_source(source_lines, node))

    return global_blocks


def _should_extract(name: str, ignore_method_names: set[str], include_name_pattern: Optional[re.Pattern] = None) -> bool:
    if name == "__init__" or name in ignore_method_names:
        return False
    if include_name_pattern and not include_name_pattern.fullmatch(name):
        return False
    return True


def _normalize_method_code(
    source_lines: List[str],
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    nested: bool,
    class_name: Optional[str],
) -> str:
    dedent = nested or class_name is not None
    return _slice_node_source(source_lines, node, dedent=dedent)


def _collect_nested_functions(
    statements: Sequence[ast.stmt],
    source_lines: List[str],
    methods: List[MethodInfo],
    class_name: Optional[str],
    ignore_method_names: set[str],
    include_name_pattern: Optional[re.Pattern],
) -> None:
    for stmt in statements:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if _should_extract(stmt.name, ignore_method_names, include_name_pattern):
                methods.append(
                    MethodInfo(
                        name=stmt.name,
                        start_line=stmt.lineno,
                        end_line=_get_node_end_lineno(stmt),
                        code=_normalize_method_code(
                            source_lines,
                            stmt,
                            nested=True,
                            class_name=class_name,
                        ),
                        class_name=class_name,
                        is_nested=True,
                        injected_vars=[],
                    )
                )
            _collect_nested_functions(
                stmt.body,
                source_lines,
                methods,
                class_name,
                ignore_method_names,
                include_name_pattern,
            )
            continue

        for child_body_name in ("body", "orelse", "finalbody"):
            child_body = getattr(stmt, child_body_name, None)
            if isinstance(child_body, list):
                _collect_nested_functions(
                    child_body,
                    source_lines,
                    methods,
                    class_name,
                    ignore_method_names,
                    include_name_pattern,
                )

        handlers = getattr(stmt, "handlers", None)
        if handlers:
            for handler in handlers:
                _collect_nested_functions(
                    handler.body,
                    source_lines,
                    methods,
                    class_name,
                    ignore_method_names,
                    include_name_pattern,
                )


def parse_source(
    source: str,
    ignore_method_names: Optional[Sequence[str]] = None,
    include_method_name_pattern: Optional[str] = None,
) -> Tuple[List[MethodInfo], Dict[str, List[str]], List[str]]:
    normalized_source = source.replace("\r\n", "\n").replace("\r", "\n")
    source_lines = normalized_source.splitlines()
    tree = ast.parse(normalized_source)
    ignored = set(ignore_method_names or [])
    include_name_pattern = re.compile(include_method_name_pattern) if include_method_name_pattern else None

    methods: List[MethodInfo] = []
    init_map = extract_init_assignments(source_lines, tree)
    global_blocks = extract_global_assignments(source_lines, tree)

    for node in getattr(tree, "body", []):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if _should_extract(node.name, ignored, include_name_pattern):
                methods.append(
                    MethodInfo(
                        name=node.name,
                        start_line=node.lineno,
                        end_line=_get_node_end_lineno(node),
                        code=_normalize_method_code(
                            source_lines,
                            node,
                            nested=False,
                            class_name=None,
                        ),
                        class_name=None,
                        is_nested=False,
                        injected_vars=[],
                    )
                )
            _collect_nested_functions(
                node.body,
                source_lines,
                methods,
                None,
                ignored,
                include_name_pattern,
            )

        elif isinstance(node, ast.ClassDef):
            class_name = node.name
            for item in node.body:
                if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if item.name == "__init__":
                    continue

                if _should_extract(item.name, ignored, include_name_pattern):
                    methods.append(
                        MethodInfo(
                            name=item.name,
                            start_line=item.lineno,
                            end_line=_get_node_end_lineno(item),
                            code=_normalize_method_code(
                                source_lines,
                                item,
                                nested=False,
                                class_name=class_name,
                            ),
                            class_name=class_name,
                            is_nested=False,
                            injected_vars=[],
                        )
                    )

                _collect_nested_functions(
                    item.body,
                    source_lines,
                    methods,
                    class_name,
                    ignored,
                    include_name_pattern,
                )

    methods.sort(key=lambda method: (method.start_line, method.end_line, method.name))
    return methods, init_map, global_blocks


def prepare_methods_with_inits(
    methods: List[MethodInfo],
    init_map: Dict[str, List[str]],
    global_blocks: List[str],
) -> List[MethodInfo]:
    prepared: List[MethodInfo] = []

    for method in methods:
        injected: List[str] = list(global_blocks)
        if method.class_name:
            injected.extend(init_map.get(method.class_name, []))

        prepared.append(
            MethodInfo(
                name=method.name,
                start_line=method.start_line,
                end_line=method.end_line,
                code=method.code,
                class_name=method.class_name,
                is_nested=method.is_nested,
                injected_vars=injected,
            )
        )

    return prepared
