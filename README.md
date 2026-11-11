# 🩺 heal-qa: Self-Healing E2E Test Locator Engine for AI & Modern Web

[![Python](https://img.shields.io/badge/python-3.14%2B-blue.svg?logo=python&logoColor=white)](https://www.python.org/)
[![Playwright](https://img.shields.io/badge/playwright-supported-2EAD33.svg?logo=playwright&logoColor=white)](https://playwright.dev/python/)
[![BeautifulSoup4](https://img.shields.io/badge/parser-bs4-brightgreen.svg)](https://www.crummy.com/software/BeautifulSoup/)
[![Tests](https://img.shields.io/badge/tests-5%2F5%20passed-success.svg)](https://pytest.org)
[![Platform](https://img.shields.io/badge/platform-windows%20%7C%20macos%20%7C%20linux-lightgrey.svg)](https://github.com)
[![License: MIT](https://img.shields.io/badge/license-MIT-yellow.svg)](LICENSE)

An open-source locator healing engine and test patcher for modern web automation. `heal-qa` prevents test suites from breaking when redesigns, refactoring, or generative AI agents modify the underlying DOM markup.

---

## 💥 The Problem: Flaky Tests and Brittle Selectors

Modern frontend applications evolve rapidly. Dynamic class names (Tailwind, CSS Modules, styled-components), redesigns, and automated updates made by autonomous coding agents frequently invalidate hardcoded CSS and XPath selectors. 

When a selector such as `.btn-old` or `#submit-v1` breaks:
- CI/CD pipelines fail unexpectedly;
- QA engineers spend hours manually inspecting snapshots and updating locators;
- Automation velocity slows down.

---

## 💡 The Solution: Multi-Factor Fuzzy Matching & Auto-Patching

`heal-qa` parses the HTML DOM tree at the point of failure and evaluates every candidate element using a calibrated 4-factor scoring algorithm:

| Factor | Weight | Description |
| :--- | :---: | :--- |
| **Visible Text & Labels** | **0.4** | Exact & fuzzy matching of text, `placeholder`, `title`, and `value`. |
| **Accessibility Attributes** | **0.3** | `aria-label`, `role` (explicit & implicit), `data-testid`, and `data-cy`. |
| **Tag Type & Ancestor Hierarchy** | **0.2** | Element tag compatibility and parent container structure. |
| **Class & ID Similarity** | **0.1** | Substring, token, and prefix similarity (`btn-*`, BEM identifiers). |

Once the optimal target element is identified, `heal-qa` generates an ultra-resilient CSS selector and safely patches your test files while preserving indentation, comments, and quoting styles.

---

## 🚀 Quickstart

### Prerequisites
- Python 3.14+ (or compatible virtual environment)

### 1. Installation

#### macOS / Linux
```bash
git clone https://github.com/your-org/heal-qa.git
cd heal-qa
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

#### Windows (PowerShell)
```powershell
git clone https://github.com/your-org/heal-qa.git
cd heal-qa
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .
```

---

## 🛠️ CLI Usage

`heal-qa` provides an interactive terminal interface built with **Typer** and **Rich**.

### 1. Inspect a Broken Selector
Analyze an HTML snapshot (file, live URL, or raw HTML) against a broken selector to view ranked candidates and confidence scores:

```bash
python -m src.cli inspect --selector ".old-btn" --html page.html --text "Submit Order"
```

*Or using the installed console script:*
```bash
heal-qa inspect --selector ".old-btn" --html page.html
```

**Example output:**
```
╭──────── heal-qa DOM Inspector ────────╮
│ Broken Selector: .old-btn             │
│ Snapshot Source: File: page.html      │
│ Expected Text: Submit Order           │
│ Confidence Threshold: 50%             │
╰───────────────────────────────────────╯
                            Candidate Match Ranking                             
┏━━━━┳━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━┓
┃ #  ┃ Candidate        ┃ Confidence ┃ Text     ┃ A11y     ┃ Tag      ┃ Class/ID ┃
┃    ┃ Selector         ┃            ┃ (40%)    ┃ (30%)    ┃ (20%)    ┃ (10%)    ┃
┡━━━━╇━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━┩
│ 1  │ .btn-primary-new │      96.0% │     1.00 │     1.00 │     1.00 │     0.60 │
│ 2  │ .container       │      48.5% │     1.00 │     0.00 │     0.30 │     0.25 │
└────┴──────────────────┴────────────┴──────────┴──────────┴──────────┴──────────┘
```

### 2. Safely Patch Test Code
Automatically replace the broken selector across your test files with full visual diff verification:

```bash
python -m src.cli patch --file tests/test_ui.py --old ".old-btn" --new ".btn-primary-new"
```

*Preview changes first with dry-run mode:*
```bash
heal-qa patch --file tests/test_ui.py --old ".old-btn" --new ".btn-primary-new" --dry-run
```

---

## 🐍 Python API Example

You can integrate `heal-qa` directly into Playwright hooks or custom test runners:

```python
from bs4 import BeautifulSoup
from src.matcher.dom_healer import DOMHealer
from src.patcher.code_patcher import TestPatcher

healer = DOMHealer(min_confidence=0.5)

# 1. Resolve broken selector
html = page.content()
new_selector, score = healer.heal_selector(
    broken_selector=".btn-old",
    html_snapshot=html,
    expected_text="Submit Order"
)

if score >= 0.5:
    print(f"Healed selector: {new_selector} (confidence: {score:.1%})")
    # 2. Patch test file on the fly
    TestPatcher().patch_test_file("tests/test_checkout.py", ".btn-old", new_selector)
```

---

## 🧪 Running Tests

Execute the full suite of unit and integration tests:

```bash
pytest -v
```

---

## 📄 License

This project is licensed under the terms of the [MIT License](LICENSE).
