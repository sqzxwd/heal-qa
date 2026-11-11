"""Unit and integration tests for heal-qa locator resolver and patcher."""

from __future__ import annotations

from pathlib import Path
from bs4 import BeautifulSoup
from typer.testing import CliRunner

from src.cli import app
from src.matcher.dom_healer import DOMHealer
from src.patcher.code_patcher import TestPatcher


def test_heal_button_class_change():
    """Verify healing button when class changes (.btn-old -> .btn-primary-new)."""
    html = """
    <!DOCTYPE html>
    <html>
      <body>
        <main>
          <div class="form-actions">
            <button class="btn-primary-new" type="submit">Submit Form</button>
            <a href="/cancel" class="link-cancel">Cancel</a>
          </div>
        </main>
      </body>
    </html>
    """
    healer = DOMHealer(min_confidence=0.5)

    # 1. Healing with class-only broken selector and expected text
    new_selector, score = healer.heal_selector(
        broken_selector=".btn-old",
        html_snapshot=html,
        expected_text="Submit Form",
        expected_tag="button",
    )
    assert score >= 0.5
    assert new_selector in (".btn-primary-new", "button.btn-primary-new")

    soup = BeautifulSoup(html, "html.parser")
    matched = soup.select(new_selector)
    assert len(matched) == 1
    assert "btn-primary-new" in matched[0].get("class", [])

    # 2. Healing without expected_text (matching by tag and class similarity / role)
    new_selector_auto, score_auto = healer.heal_selector(
        broken_selector="button.btn-old",
        html_snapshot=html,
    )
    assert score_auto >= 0.5
    assert "btn-primary-new" in new_selector_auto


def test_heal_input_by_placeholder_and_aria_label_on_id_change():
    """Verify healing input element when id changes, matching via placeholder or aria-label."""
    html = """
    <form id="auth-form">
      <div class="form-group">
        <label for="new-email-field-v2">Your Email</label>
        <input id="new-email-field-v2"
               name="email"
               type="email"
               placeholder="Enter your email address"
               aria-label="Email Address Field" />
      </div>
      <button type="submit">Log in</button>
    </form>
    """
    healer = DOMHealer(min_confidence=0.5)
    soup = BeautifulSoup(html, "html.parser")

    # 1. Matching by placeholder when id changed from #old-email-field
    new_selector_ph, score_ph = healer.heal_selector(
        broken_selector="input#old-email-field",
        html_snapshot=html,
        expected_text="Enter your email address",
    )
    assert score_ph >= 0.5
    matched_ph = soup.select(new_selector_ph)
    assert len(matched_ph) == 1
    assert matched_ph[0]["id"] == "new-email-field-v2"

    # 2. Matching by aria-label when id changed
    new_selector_aria, score_aria = healer.heal_selector(
        broken_selector="#old-email-field",
        html_snapshot=html,
        expected_text="Email Address Field",
    )
    assert score_aria >= 0.5
    matched_aria = soup.select(new_selector_aria)
    assert len(matched_aria) == 1
    assert matched_aria[0]["id"] == "new-email-field-v2"


def test_confidence_threshold_prevents_false_healing():
    """Verify that candidate scores < 0.5 do not trigger false healing."""
    unrelated_html = """
    <div class="marketing-footer">
      <nav>
        <a href="/about">About Us</a>
        <a href="/terms">Terms of Service</a>
      </nav>
      <p class="legal-notice">Copyright 2026. All rights reserved.</p>
    </div>
    """
    healer = DOMHealer(min_confidence=0.5)

    # Completely unrelated broken selector
    new_selector, score = healer.heal_selector(
        broken_selector="button#checkout-payment-btn",
        html_snapshot=unrelated_html,
        expected_text="Pay $99 Now",
    )
    # Score should be strictly below 0.5
    assert score < 0.5
    # Should not return a false replacement selector
    assert new_selector == ""


def test_patch_test_file_correct_string_update(tmp_path: Path):
    """Verify that test file lines are correctly updated while preserving quotes and indentation."""
    original_code = (
        'import pytest\n'
        'from playwright.sync_api import Page, expect\n'
        '\n'
        'def test_user_checkout(page: Page):\n'
        '    page.goto("https://app.example.com")\n'
        '    # Double-quoted call with 4 spaces indent\n'
        '    page.locator(".btn-old").click()\n'
        "    # Single-quoted call with 4 spaces indent\n"
        "    page.click('.btn-old')\n"
        '    # Different locator that should not be touched\n'
        '    page.fill("#user-email", "customer@example.com")\n'
        '    # Assertion\n'
        '    expect(page.locator(".btn-old")).to_be_visible()\n'
    )
    test_file = tmp_path / "test_checkout.py"
    test_file.write_text(original_code, encoding="utf-8")

    patcher = TestPatcher()

    # Verify diff before modifying
    diff = patcher.get_diff(test_file, ".btn-old", ".btn-primary-new")
    assert "-    page.locator(\".btn-old\").click()" in diff
    assert "+    page.locator(\".btn-primary-new\").click()" in diff
    assert "-    page.click('.btn-old')" in diff
    assert "+    page.click('.btn-primary-new')" in diff

    # Apply patch
    result = patcher.patch_test_file(test_file, ".btn-old", ".btn-primary-new")
    assert result is True

    updated_code = test_file.read_text(encoding="utf-8")

    # Check preserved indentation and quote styles
    assert '    page.locator(".btn-primary-new").click()' in updated_code
    assert "    page.click('.btn-primary-new')" in updated_code
    assert '    expect(page.locator(".btn-primary-new")).to_be_visible()' in updated_code

    # Old selector should no longer exist
    assert ".btn-old" not in updated_code

    # Untouched lines must remain unchanged
    assert '    page.fill("#user-email", "customer@example.com")' in updated_code
    assert "    # Double-quoted call with 4 spaces indent" in updated_code

    # Second call should be idempotent and return False
    second_result = patcher.patch_test_file(test_file, ".btn-old", ".btn-primary-new")
    assert second_result is False


def test_cli_inspect_and_patch_commands(tmp_path: Path):
    """Test CLI inspect and patch commands via Typer CliRunner."""
    runner = CliRunner()
    sample_html = '<button class="btn-primary-new">Submit</button>'

    # 1. Test inspect command
    inspect_res = runner.invoke(
        app,
        [
            "inspect",
            "--selector",
            ".btn-old",
            "--html",
            sample_html,
            "--text",
            "Submit",
            "--tag",
            "button",
        ],
    )
    assert inspect_res.exit_code == 0
    assert "Candidate Match Ranking" in inspect_res.output
    assert "btn-primary-new" in inspect_res.output

    # 2. Test patch command
    test_file = tmp_path / "test_sample.py"
    test_file.write_text('    page.locator(".btn-old").click()\n', encoding="utf-8")

    patch_res = runner.invoke(
        app,
        [
            "patch",
            "--file",
            str(test_file),
            "--old",
            ".btn-old",
            "--new",
            ".btn-primary-new",
        ],
    )
    assert patch_res.exit_code == 0
    assert "Successfully updated test file" in patch_res.output
    assert 'page.locator(".btn-primary-new").click()' in test_file.read_text(encoding="utf-8")
