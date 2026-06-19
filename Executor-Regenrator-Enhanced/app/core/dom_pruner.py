from typing import Optional, List, Set
from bs4 import BeautifulSoup, FeatureNotFound, Tag
try:
    from bs4 import XMLParsedAsHTMLWarning
except ImportError:  # pragma: no cover - older BeautifulSoup versions
    XMLParsedAsHTMLWarning = Warning
import re
import warnings


class DomPruner:
    """
    Intelligent DOM Pruner for LLM-driven automation systems.

    Compresses raw HTML into a structured nested AST-like tag tree
    containing only interactive nodes, matching keyword nodes,
    and their essential structural ancestor containers.
    """

    MAX_CHARS = 5000

    INTERACTIVE_TAGS = {
        "button", "a", "input", "select", "textarea",
        "form", "label", "option"
    }

    APPIUM_INTERACTIVE_SUFFIXES = (
        "Button",
        "ImageButton",
        "EditText",
        "Switch",
        "TextView",
        "CheckedTextView",
        "RadioButton",
        "CheckBox",
    )

    PRIORITY_TAG_ORDER = [
        "button",
        "a",
        "input",
        "select",
        "textarea",
        "form",
        "label",
    ]

    IMPORTANT_ATTRS = [
        "id", "name", "class", "href",
        "value", "type", "role", "placeholder",
        "text", "content-desc", "resource-id",
        "bounds", "clickable", "enabled", "displayed"
    ]

    @classmethod
    def prune(
        cls,
        dom_snapshot: Optional[str],
        keyword: Optional[str] = None,
        framework: str = "playwright",
    ) -> Optional[str]:

        if not dom_snapshot:
            return None

        soup = cls._parse_dom(dom_snapshot, framework=framework)

        # Remove scripts, styles, and other metadata
        for tag in soup(["script", "style", "meta", "link", "noscript"]):
            tag.decompose()

        body = soup.find("hierarchy") or soup.body or soup

        if not keyword:
            keep_elements = body.find_all(cls._is_interactive)
            return cls._serialize_tree(body, keep_elements)[:cls.MAX_CHARS]

        keyword_lower = keyword.lower()

        # Collect candidate tags containing the keyword in text or attributes
        candidates = []
        for element in body.find_all(True):
            if not isinstance(element, Tag):
                continue

            text = element.get_text(separator=" ", strip=True)
            attrs_text = " ".join(
                str(element.attrs.get(attr, ""))
                for attr in cls.IMPORTANT_ATTRS
            )
            searchable_blob = f"{text} {attrs_text}".lower()

            if keyword_lower in searchable_blob:
                score = cls._score_element(element)
                candidates.append((score, element))

        if not candidates:
            keep_elements = body.find_all(cls._is_interactive)
            return cls._serialize_tree(body, keep_elements)[:cls.MAX_CHARS]

        # Rank by score (highest priority first)
        candidates.sort(key=lambda x: x[0], reverse=True)

        # Deduplicate nested matches to keep it clean
        unique_elements = cls._deduplicate([el for _, el in candidates])

        # Serialize AST
        result = cls._serialize_tree(body, unique_elements)

        return result[:cls.MAX_CHARS]

    @classmethod
    def _parse_dom(cls, dom_snapshot: str, *, framework: str) -> BeautifulSoup:
        is_xml = (
            framework == "appium"
            or dom_snapshot.lstrip().startswith("<?xml")
            or "<hierarchy" in dom_snapshot[:500].lower()
        )
        if is_xml:
            try:
                return BeautifulSoup(dom_snapshot, "xml")
            except FeatureNotFound:
                with warnings.catch_warnings():
                    warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
                    return BeautifulSoup(dom_snapshot, "html.parser")

        return BeautifulSoup(dom_snapshot, "html.parser")

    @classmethod
    def _is_interactive(cls, element: Tag) -> bool:
        tag = element.name or ""
        if tag in cls.INTERACTIVE_TAGS:
            return True
        if any(tag.endswith(suffix) for suffix in cls.APPIUM_INTERACTIVE_SUFFIXES):
            return True
        return (
            str(element.get("clickable", "")).lower() == "true"
            or str(element.get("focusable", "")).lower() == "true"
        )

    @classmethod
    def _score_element(cls, element: Tag) -> int:
        """
        Actionability scoring.
        Higher = more likely clickable/important.
        """
        score = 0
        tag = element.name

        if cls._is_interactive(element):
            score += 50

        if tag in cls.PRIORITY_TAG_ORDER:
            score += 20

        if element.has_attr("id"):
            score += 10

        if element.has_attr("name"):
            score += 10

        if element.has_attr("role"):
            score += 10
            # Boost for explicit interactive roles on general containers
            if element.get("role") in {"button", "link", "menuitem", "option", "tab", "checkbox", "radio"}:
                score += 40

        # Custom interactive properties (onclick, @click, cursor: pointer style)
        if element.has_attr("onclick") or element.has_attr("@click"):
            score += 40

        style = element.get("style", "")
        if isinstance(style, str) and ("cursor:pointer" in style.replace(" ", "") or "cursor: pointer" in style):
            score += 30

        text_length = len(element.get_text(strip=True))
        score += min(text_length, 30)

        return score

    @staticmethod
    def _deduplicate(elements: List[Tag]) -> List[Tag]:
        """
        Removes nested duplicates.
        If parent and child both match, prefer the more specific (child).
        """
        unique = []
        for el in elements:
            if any(el in parent.descendants for parent in unique):
                continue
            unique.append(el)
        return unique

    @classmethod
    def _serialize_tree(cls, root: Tag, keep_elements: List[Tag]) -> str:
        """
        Converts DOM elements into a compact hierarchical tag-tree AST.
        """
        targets = set(keep_elements)
        ancestors = set()

        for el in keep_elements:
            ancestors.add(el)
            parent = el.parent
            while parent and parent.name not in (None, "[document]", "html"):
                ancestors.add(parent)
                parent = parent.parent

        lines = []

        def traverse(node: Tag, depth: int):
            if not isinstance(node, Tag):
                return
            if node not in ancestors:
                return

            tag = node.name
            attrs = []
            for attr in cls.IMPORTANT_ATTRS:
                if attr in node.attrs:
                    val = node.attrs[attr]
                    if isinstance(val, list):
                        val = " ".join(val)
                    attrs.append(f'{attr}="{val}"')

            # Capture text for target nodes or interactive nodes
            text = ""
            if node in targets or cls._is_interactive(node):
                text = node.get_text(separator=" ", strip=True)
                if len(text) > 60:
                    text = text[:57] + "..."

            attrs_str = " " + " ".join(attrs) if attrs else ""
            text_str = f' text="{text}"' if text else ""
            indent = "  " * depth

            lines.append(f"{indent}<{tag}{attrs_str}{text_str}>")

            for child in node.children:
                if isinstance(child, Tag):
                    traverse(child, depth + 1)

            lines.append(f"{indent}</{tag}>")

        body = root.body or root
        traverse(body, 0)
        return "\n".join(lines)
