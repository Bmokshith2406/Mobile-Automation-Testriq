import ast
import unittest

from app.services.extraction_service import extract_methods_from_source


class ExtractionServiceTests(unittest.TestCase):
    def test_multiline_context_is_preserved_and_parseable(self):
        source = """
CONST = (
    "abc"
)

class Page:
    def __init__(self, page):
        self.page = page
        self.selector = (
            "#id"
        )

    def open(self):
        return self.selector
"""
        result = extract_methods_from_source(
            source,
            max_chars_per_chunk=20_000,
            ignore_method_names=[],
        )

        self.assertEqual(len(result.methods), 1)
        method = result.methods[0]
        combined = "\n".join([*method.injected_vars, "", method.code]).strip()
        ast.parse(combined)
        self.assertIn('CONST = (\n    "abc"\n)', combined)
        self.assertIn('self.selector = (\n    "#id"\n)', combined)
        self.assertTrue(method.code.startswith("def open(self):"))

    def test_nested_functions_inside_control_flow_are_extracted(self):
        source = """
def outer():
    if True:
        def inner():
            def deeper():
                return 1
            return deeper()
    return inner()
"""
        result = extract_methods_from_source(
            source,
            max_chars_per_chunk=20_000,
            ignore_method_names=[],
        )

        names = [method.name for method in result.methods]
        self.assertEqual(names, ["outer", "inner", "deeper"])

    def test_common_method_names_are_not_silently_filtered(self):
        source = """
class LoginPage:
    def open(self):
        return "ok"
"""
        result = extract_methods_from_source(
            source,
            max_chars_per_chunk=20_000,
            ignore_method_names=[],
        )

        self.assertEqual(len(result.methods), 1)
        self.assertEqual(result.methods[0].name, "open")

    def test_include_method_name_pattern_filters_to_generated_steps(self):
        source = """
async def _guarded_step(page):
    return None

async def _step_0_abcdef123456(page):
    await page.click("text=Login")

async def test_flow():
    return None
"""
        result = extract_methods_from_source(
            source,
            max_chars_per_chunk=20_000,
            ignore_method_names=[],
            include_method_name_pattern=r"^_step_\d+_[a-f0-9]{12}$",
        )

        self.assertEqual(len(result.methods), 1)
        self.assertEqual(result.methods[0].name, "_step_0_abcdef123456")


if __name__ == "__main__":
    unittest.main()
