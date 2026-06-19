from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import (
    Any,
    Callable,
    Dict,
    Iterable,
    Iterator,
    List,
    Protocol,
    Tuple,
)


class MethodInfoLike(Protocol):
    """
    Structural protocol representing an extracted method.

    Implemented by MethodInfo objects produced by the
    Playwright Python AST extraction pipeline.
    """

    name: str
    start_line: int
    end_line: int
    code: str
    class_name: str
    is_nested: bool
    injected_vars: List[str]


@dataclass
class Chunk:
    """
    Represents a logical chunk of extracted methods.

    Chunks are created to limit payload size for
    downstream processing (LLMs, embeddings, storage).
    """

    index: int
    methods: List[MethodInfoLike]
    total_chars: int
    total_methods: int

    def __repr__(self) -> str:
        return (
            f"Chunk(index={self.index}, "
            f"total_methods={self.total_methods}, "
            f"total_chars={self.total_chars})"
        )


def _estimate_method_size(m: MethodInfoLike, buffer: int = 200) -> int:
    """
    Estimate the character size contribution of a method.

    Includes:
    - method source code
    - injected variable declarations
    - a small safety buffer
    """
    injected_vars = m.injected_vars or []
    injected_len = sum(len(v) for v in injected_vars) + len(injected_vars)
    return len(m.code) + injected_len + buffer


def build_chunks(
    methods: List[MethodInfoLike],
    max_chars_per_chunk: int = 20_000,
) -> List[Chunk]:
    """
    Group extracted methods into size-bounded chunks.

    Used by the Playwright Python Method Extraction service
    to control memory usage and downstream processing limits.
    """

    chunks: List[Chunk] = []
    current: List[MethodInfoLike] = []
    current_chars = 0
    idx = 0

    # Ensure deterministic ordering
    methods = sorted(methods, key=lambda m: m.start_line)

    for m in methods:
        m_size = _estimate_method_size(m)
        would_exceed = current_chars + m_size > max_chars_per_chunk

        if current and would_exceed:
            chunks.append(
                Chunk(
                    index=idx,
                    methods=current,
                    total_chars=current_chars,
                    total_methods=len(current),
                )
            )
            idx += 1
            current = []
            current_chars = 0

        # Handle oversized single methods
        if not current and m_size > max_chars_per_chunk:
            chunks.append(
                Chunk(
                    index=idx,
                    methods=[m],
                    total_chars=m_size,
                    total_methods=1,
                )
            )
            idx += 1
            continue

        current.append(m)
        current_chars += m_size

    if current:
        chunks.append(
            Chunk(
                index=idx,
                methods=current,
                total_chars=current_chars,
                total_methods=len(current),
            )
        )

    return chunks


def chunk_to_text(chunk: Chunk, separator: str = "\n\n") -> str:
    """
    Convert a chunk into a single text block.

    Injected variables are placed before method code
    to preserve execution context.
    """
    parts: List[str] = []

    for m in chunk.methods:
        if m.injected_vars:
            parts.extend(m.injected_vars)
        parts.append(m.code)

    return separator.join(parts).rstrip()


def iter_chunk_texts(
    methods: List[MethodInfoLike],
    max_chars_per_chunk: int = 20_000,
) -> Iterator[Tuple[int, str]]:
    """
    Yield (chunk_index, chunk_text) pairs lazily.
    """
    for c in build_chunks(methods, max_chars_per_chunk=max_chars_per_chunk):
        yield c.index, chunk_to_text(c)


def process_chunks_parallel(
    chunks: List[Chunk],
    worker_fn: Callable[[Chunk], Any],
    max_workers: int = 4,
    collect_results: bool = True,
) -> List[Any]:
    """
    Process chunks concurrently using a thread pool.

    Designed for CPU-bound or blocking post-processing
    steps in the Playwright extraction pipeline.
    """

    results_by_index: Dict[int, Any] = {}

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(worker_fn, chunk): chunk.index
            for chunk in chunks
        }

        for future in as_completed(futures):
            idx = futures[future]
            try:
                results_by_index[idx] = future.result()
            except Exception as exc:
                results_by_index[idx] = exc

    if collect_results:
        return [results_by_index[i] for i in range(len(chunks))]

    return []


def approximate_total_size(methods: List[MethodInfoLike]) -> int:
    """
    Estimate total character size of all extracted methods.
    """
    return sum(_estimate_method_size(m) for m in methods)
