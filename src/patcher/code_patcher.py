"""Safe code patcher for test locators with format and quote preservation."""

from __future__ import annotations

import difflib
import re
from pathlib import Path


class TestPatcher:
    """Safe source code patcher for test locators.

    Preserves original indentation, formatting, and quote styles (single vs double quotes).
    """

    def patch_test_file(
        self, file_path: str | Path, old_selector: str, new_selector: str
    ) -> bool:
        """Patch test file replacing old_selector with new_selector in locator calls.

        Args:
            file_path: Path to the test file.
            old_selector: Broken selector string to find.
            new_selector: Healed replacement selector string.

        Returns:
            bool: True if the file was modified, False if no occurrences found.
        """
        path = Path(file_path)
        if not path.is_file():
            raise FileNotFoundError(f"Test file not found: {file_path}")

        content = path.read_text(encoding="utf-8")
        patched_content, modified = self.patch_content(content, old_selector, new_selector)

        if modified:
            path.write_text(patched_content, encoding="utf-8")

        return modified

    def patch_content(
        self, content: str, old_selector: str, new_selector: str
    ) -> tuple[str, bool]:
        """Patch string content replacing old_selector while preserving indentation and quotes."""
        lines = content.splitlines(keepends=True)
        modified = False
        new_lines: list[str] = []

        # Common locator and Playwright action patterns
        action_keyword = re.compile(
            r"(?:locator|click|fill|type|press|hover|check|uncheck|wait_for_selector|"
            r"select_option|query_selector|eval_on_selector|expect|get_by_)"
        )

        for line in lines:
            patched_line = line

            # Check single-quoted occurrence: 'old_selector'
            old_sq = f"'{old_selector}'"
            if old_sq in line:
                if "'" in new_selector and '"' not in new_selector:
                    safe_new = new_selector.replace("'", '"')
                    rep = f"'{safe_new}'"
                elif "'" in new_selector:
                    rep = f'"{new_selector}"'
                else:
                    rep = f"'{new_selector}'"
                patched_line = patched_line.replace(old_sq, rep)

            # Check double-quoted occurrence: "old_selector"
            old_dq = f'"{old_selector}"'
            if old_dq in line:
                if '"' in new_selector and "'" not in new_selector:
                    safe_new = new_selector.replace('"', "'")
                    rep = f'"{safe_new}"'
                elif '"' in new_selector:
                    rep = f"'{new_selector}'"
                else:
                    rep = f'"{new_selector}"'
                patched_line = patched_line.replace(old_dq, rep)

            if patched_line != line:
                modified = True
                new_lines.append(patched_line)
            else:
                new_lines.append(line)

        return "".join(new_lines), modified

    def get_diff(
        self, file_path: str | Path, old_selector: str, new_selector: str
    ) -> str:
        """Generate unified diff showing changes without modifying the file on disk."""
        path = Path(file_path)
        if not path.is_file():
            raise FileNotFoundError(f"Test file not found: {file_path}")

        original = path.read_text(encoding="utf-8")
        patched, modified = self.patch_content(original, old_selector, new_selector)

        if not modified:
            return ""

        diff_lines = list(
            difflib.unified_diff(
                original.splitlines(keepends=True),
                patched.splitlines(keepends=True),
                fromfile=f"a/{path.name}",
                tofile=f"b/{path.name}",
            )
        )
        return "".join(diff_lines)
