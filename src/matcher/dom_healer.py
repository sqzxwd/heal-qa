"""DOM-based locator resolver and multi-factor healer for UI tests."""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from typing import Any

from bs4 import BeautifulSoup, Tag


@dataclass
class Candidate:
    """Represents a candidate element in the DOM with scoring breakdown."""

    element: Tag
    selector: str
    score: float
    text_score: float
    a11y_score: float
    tag_score: float
    class_id_score: float
    details: dict[str, Any] = field(default_factory=dict)


def _tokenize(text: str) -> set[str]:
    """Extract lowercase alphanumeric tokens from string."""
    return set(re.findall(r"[a-zA-Z0-9]+", text.lower()))


def _calc_string_similarity(a: str | None, b: str | None) -> float:
    """Calculate normalized similarity ratio (0.0 to 1.0) between two strings."""
    if not a or not b:
        return 0.0

    a_clean = a.strip().lower()
    b_clean = b.strip().lower()

    if a_clean == b_clean:
        return 1.0

    # Substring match bonus
    if a_clean in b_clean or b_clean in a_clean:
        min_len = len(min(a_clean, b_clean, key=len))
        max_len = len(max(a_clean, b_clean, key=len))
        ratio = min_len / max_len if max_len > 0 else 0.0
        return round(min(1.0, 0.75 + 0.25 * ratio), 4)

    # SequenceMatcher ratio
    seq_ratio = difflib.SequenceMatcher(None, a_clean, b_clean).ratio()

    # Common prefix bonus before hyphen or underscore (e.g. btn-old vs btn-primary-new)
    prefix_a = a_clean.split("-")[0].split("_")[0]
    prefix_b = b_clean.split("-")[0].split("_")[0]
    if prefix_a and prefix_a == prefix_b and len(prefix_a) >= 2:
        seq_ratio = max(seq_ratio, 0.6)

    # Token overlap bonus
    tokens_a = _tokenize(a_clean)
    tokens_b = _tokenize(b_clean)
    if tokens_a and tokens_b:
        overlap = len(tokens_a & tokens_b) / len(tokens_a | tokens_b)
        return round(max(seq_ratio, overlap), 4)

    return round(seq_ratio, 4)


def _infer_implicit_role(tag: Tag) -> str:
    """Infer WAI-ARIA role based on HTML tag and attributes."""
    name = tag.name.lower()
    tag_type = (tag.get("type") or "").lower()

    if name == "button":
        return "button"
    if name == "input":
        if tag_type in ("button", "submit", "reset"):
            return "button"
        if tag_type == "checkbox":
            return "checkbox"
        if tag_type == "radio":
            return "radio"
        return "textbox"
    if name == "textarea":
        return "textbox"
    if name == "a" and tag.get("href"):
        return "link"
    if name == "select":
        return "combobox"
    if name in ("h1", "h2", "h3", "h4", "h5", "h6"):
        return "heading"
    if name == "nav":
        return "navigation"
    if name == "main":
        return "main"
    if name == "form":
        return "form"
    if name == "dialog":
        return "dialog"
    return ""


def _parse_broken_selector(selector: str) -> dict[str, Any]:
    """Parse CSS/Playwright selector into structured attributes."""
    parts = re.split(r"\s*>\s*|\s+", selector.strip())
    target = parts[-1]
    ancestor_parts = parts[:-1]

    text = None
    # Playwright :has-text("...") or :text("...")
    m_text = re.search(r":(?:has-text|text)\([\"\']?([^\'\"\)]+)[\"\']?\)", selector)
    if m_text:
        text = m_text.group(1)
    elif selector.startswith("text="):
        text = selector[5:].strip("\"'")

    attrs: dict[str, str] = {}
    for m in re.finditer(r"\[([a-zA-Z0-9_\-]+)(?:[*^$|~]?=[\"\']?([^\'\"\]]+)[\"\']?)?\]", target):
        attrs[m.group(1)] = m.group(2) if m.group(2) is not None else ""

    clean_target = re.sub(r"\[[^\]]+\]", "", target)
    clean_target = re.sub(r":(?:has-text|text)\([^)]+\)", "", clean_target)

    m_id = re.search(r"#([a-zA-Z0-9_\-]+)", clean_target)
    elem_id = m_id.group(1) if m_id else None

    classes = re.findall(r"\.([a-zA-Z0-9_\-]+)", clean_target)

    m_tag = re.match(r"^([a-zA-Z][a-zA-Z0-9]*)", clean_target)
    tag = m_tag.group(1).lower() if m_tag else None

    # Ancestor tags
    ancestor_tags: list[str] = []
    for anc in ancestor_parts:
        m = re.match(r"^([a-zA-Z][a-zA-Z0-9]*)", anc)
        if m:
            ancestor_tags.append(m.group(1).lower())

    # Collect all tokens from the broken selector
    tokens: set[str] = set()
    if tag:
        tokens.update(_tokenize(tag))
    if elem_id:
        tokens.update(_tokenize(elem_id))
    for c in classes:
        tokens.update(_tokenize(c))
    for k, v in attrs.items():
        tokens.update(_tokenize(k))
        if v:
            tokens.update(_tokenize(v))
    if text:
        tokens.update(_tokenize(text))

    return {
        "raw": selector,
        "tag": tag,
        "id": elem_id,
        "classes": classes,
        "attrs": attrs,
        "text": text,
        "ancestor_tags": ancestor_tags,
        "tokens": tokens,
    }


class DOMHealer:
    """Self-healing locator resolver using multi-factor DOM tree fuzzy matching."""

    # Weights for multi-factor scoring
    WEIGHT_TEXT = 0.4
    WEIGHT_A11Y = 0.3
    WEIGHT_TAG = 0.2
    WEIGHT_CLASS_ID = 0.1

    def __init__(self, min_confidence: float = 0.5):
        """Initialize DOMHealer with minimum confidence threshold."""
        self.min_confidence = min_confidence

    def heal_selector(
        self,
        broken_selector: str,
        html_snapshot: str,
        expected_text: str | None = None,
        expected_tag: str | None = None,
    ) -> tuple[str, float]:
        """Find the most reliable replacement selector and its confidence score.

        Evaluates candidates with multi-factor scoring:
        1. Visible text / placeholder / title (weight 0.4)
        2. Accessibility attributes: aria-label, role, data-testid (weight 0.3)
        3. Tag type and parent structure (weight 0.2)
        4. Class similarity or ID substrings (weight 0.1)

        Returns:
            tuple[str, float]: (new_selector, confidence_score).
            If best score < min_confidence, returns ("", score) to avoid false healing.
        """
        candidates = self.find_candidates(
            broken_selector=broken_selector,
            html_snapshot=html_snapshot,
            expected_text=expected_text,
            expected_tag=expected_tag,
        )

        if not candidates:
            return "", 0.0

        best = candidates[0]
        if best.score < self.min_confidence:
            return "", best.score

        return best.selector, best.score

    def find_candidates(
        self,
        broken_selector: str,
        html_snapshot: str,
        expected_text: str | None = None,
        expected_tag: str | None = None,
    ) -> list[Candidate]:
        """Parse HTML, rank all candidate elements, and generate reliable selectors."""
        if not html_snapshot or not html_snapshot.strip():
            return []

        soup = BeautifulSoup(html_snapshot, "html.parser")
        parsed = _parse_broken_selector(broken_selector)

        # Filter out non-rendered/invisible document tags
        excluded_tags = {"html", "head", "meta", "link", "script", "style", "noscript"}
        raw_elements = [
            tag
            for tag in soup.find_all(True)
            if tag.name.lower() not in excluded_tags
        ]

        if not raw_elements:
            return []

        candidates: list[Candidate] = []

        for elem in raw_elements:
            score, text_score, a11y_score, tag_score, class_id_score, details = (
                self._score_element(
                    elem=elem,
                    parsed=parsed,
                    expected_text=expected_text,
                    expected_tag=expected_tag,
                )
            )

            selector = self._generate_resilient_selector(
                candidate=elem,
                soup=soup,
                broken_selector=broken_selector,
                parsed=parsed,
                details=details,
            )

            candidates.append(
                Candidate(
                    element=elem,
                    selector=selector,
                    score=round(score, 4),
                    text_score=round(text_score, 4),
                    a11y_score=round(a11y_score, 4),
                    tag_score=round(tag_score, 4),
                    class_id_score=round(class_id_score, 4),
                    details=details,
                )
            )

        # Sort descending by total score, then by specific scores
        candidates.sort(
            key=lambda c: (c.score, c.text_score, c.a11y_score, c.tag_score),
            reverse=True,
        )
        return candidates

    def _score_element(
        self,
        elem: Tag,
        parsed: dict[str, Any],
        expected_text: str | None,
        expected_tag: str | None,
    ) -> tuple[float, float, float, float, float, dict[str, Any]]:
        """Score a single DOM element against expected selector signals."""
        details: dict[str, Any] = {}

        # 1. Text factor (weight 0.4)
        text_score, text_match_type = self._calc_text_score(elem, parsed, expected_text)
        details["text_match"] = text_match_type

        # 2. Accessibility factor (weight 0.3)
        a11y_score, a11y_match_type = self._calc_a11y_score(elem, parsed, expected_text, expected_tag)
        details["a11y_match"] = a11y_match_type

        # 3. Tag & Parent factor (weight 0.2)
        tag_score, tag_match_type = self._calc_tag_score(elem, parsed, expected_tag)
        details["tag_match"] = tag_match_type

        # 4. Class & ID factor (weight 0.1)
        class_id_score, class_match_type = self._calc_class_id_score(elem, parsed)
        details["class_id_match"] = class_match_type

        total_score = (
            self.WEIGHT_TEXT * text_score
            + self.WEIGHT_A11Y * a11y_score
            + self.WEIGHT_TAG * tag_score
            + self.WEIGHT_CLASS_ID * class_id_score
        )

        return total_score, text_score, a11y_score, tag_score, class_id_score, details

    def _calc_text_score(
        self, elem: Tag, parsed: dict[str, Any], expected_text: str | None
    ) -> tuple[float, str]:
        """Calculate factor 1: visible text / placeholder / title."""
        elem_text = elem.get_text(separator=" ", strip=True)
        elem_placeholder = str(elem.get("placeholder", "")).strip()
        elem_title = str(elem.get("title", "")).strip()
        elem_value = str(elem.get("value", "")).strip()
        elem_alt = str(elem.get("alt", "")).strip()

        candidate_texts = [t for t in (elem_text, elem_placeholder, elem_title, elem_value, elem_alt) if t]

        target_text = expected_text or parsed.get("text") or parsed.get("attrs", {}).get("placeholder") or parsed.get("attrs", {}).get("title")

        if target_text:
            best_sim = 0.0
            matched_source = ""
            for t in candidate_texts:
                sim = _calc_string_similarity(target_text, t)
                if sim > best_sim:
                    best_sim = sim
                    matched_source = t
            return best_sim, f"matched '{matched_source}' with target '{target_text}'"

        # If no explicit target text, check if candidate contains selector tokens (e.g. from id or class)
        tokens = parsed.get("tokens", set())
        if tokens and candidate_texts:
            best_token_sim = 0.0
            for t in candidate_texts:
                t_tokens = _tokenize(t)
                if tokens & t_tokens:
                    overlap_ratio = len(tokens & t_tokens) / len(tokens)
                    sim = min(1.0, 0.7 + 0.3 * overlap_ratio)
                    if sim > best_token_sim:
                        best_token_sim = sim
            if best_token_sim > 0.0:
                return best_token_sim, "token overlap with selector"

        return 0.0, "none"

    def _calc_a11y_score(
        self,
        elem: Tag,
        parsed: dict[str, Any],
        expected_text: str | None,
        expected_tag: str | None,
    ) -> tuple[float, str]:
        """Calculate factor 2: accessibility attributes (aria-label, role, data-testid)."""
        elem_aria = str(elem.get("aria-label", "")).strip()
        elem_testid = (
            elem.get("data-testid")
            or elem.get("data-test")
            or elem.get("data-cy")
            or ""
        )
        elem_testid = str(elem_testid).strip()
        elem_role = str(elem.get("role", "")).strip() or _infer_implicit_role(elem)

        # 1. data-testid matching
        target_testid = (
            parsed.get("attrs", {}).get("data-testid")
            or parsed.get("attrs", {}).get("data-test")
            or parsed.get("attrs", {}).get("data-cy")
            or ""
        )
        testid_sim = 0.0
        if elem_testid:
            if target_testid:
                testid_sim = _calc_string_similarity(target_testid, elem_testid)
            elif parsed.get("id"):
                testid_sim = _calc_string_similarity(parsed["id"], elem_testid)

        # 2. aria-label matching
        target_aria = parsed.get("attrs", {}).get("aria-label") or expected_text
        aria_sim = 0.0
        if elem_aria:
            if target_aria:
                aria_sim = _calc_string_similarity(target_aria, elem_aria)
            else:
                tokens = parsed.get("tokens", set())
                if tokens & _tokenize(elem_aria):
                    aria_sim = 0.85

        # 3. role matching
        target_role = parsed.get("attrs", {}).get("role", "").lower()
        if not target_role:
            target_tag = expected_tag or parsed.get("tag")
            if target_tag == "button" or any("btn" in c for c in parsed.get("classes", [])):
                target_role = "button"
            elif target_tag == "input":
                target_role = "textbox"

        role_sim = 0.0
        if elem_role and target_role:
            if elem_role.lower() == target_role:
                role_sim = 1.0
            elif elem_role in ("button", "link") and target_role in ("button", "link"):
                role_sim = 0.7

        # Combine accessibility scores
        if testid_sim > 0.0 or aria_sim > 0.0:
            strong_score = max(testid_sim, aria_sim)
            if role_sim > 0.0:
                final_a11y = min(1.0, 0.7 * strong_score + 0.3 * role_sim)
            else:
                final_a11y = strong_score
            return final_a11y, "testid/aria matched"

        if role_sim > 0.0:
            return role_sim, "role matched"

        return 0.0, "none"

    def _calc_tag_score(
        self, elem: Tag, parsed: dict[str, Any], expected_tag: str | None
    ) -> tuple[float, str]:
        """Calculate factor 3: tag type and parent hierarchy structure."""
        target_tag = (expected_tag or parsed.get("tag") or "").lower()
        if not target_tag:
            # Infer button from 'btn' class
            if any("btn" in c for c in parsed.get("classes", [])):
                target_tag = "button"

        elem_tag = elem.name.lower()

        # Tag match
        if target_tag:
            if elem_tag == target_tag:
                tag_match = 1.0
            elif {elem_tag, target_tag} <= {"button", "input"}:
                tag_match = 0.8
            elif {elem_tag, target_tag} <= {"input", "textarea"}:
                tag_match = 0.7
            else:
                tag_match = 0.0
        else:
            tag_match = 0.6  # Neutral when no tag specified

        # Parent hierarchy match
        ancestor_targets = parsed.get("ancestor_tags", [])
        if ancestor_targets:
            parent_tags = [p.name.lower() for p in elem.parents if p.name]
            matched = sum(1 for anc in ancestor_targets if anc in parent_tags)
            parent_match = matched / len(ancestor_targets)
        else:
            parent_match = 1.0

        final_tag_score = round(0.7 * tag_match + 0.3 * parent_match, 4)
        return final_tag_score, f"tag={elem_tag}, target={target_tag or 'any'}"

    def _calc_class_id_score(
        self, elem: Tag, parsed: dict[str, Any]
    ) -> tuple[float, str]:
        """Calculate factor 4: class similarity or ID substrings."""
        target_classes = parsed.get("classes", [])
        elem_classes = elem.get("class", [])
        if isinstance(elem_classes, str):
            elem_classes = [elem_classes]

        class_sim = 0.0
        if target_classes and elem_classes:
            best_pair = 0.0
            for tc in target_classes:
                for ec in elem_classes:
                    sim = _calc_string_similarity(tc, ec)
                    if sim > best_pair:
                        best_pair = sim
            class_sim = best_pair

        target_id = parsed.get("id")
        elem_id = str(elem.get("id", "")).strip()

        id_sim = 0.0
        if target_id and elem_id:
            id_sim = _calc_string_similarity(target_id, elem_id)

        if target_classes and target_id:
            final_class_id = max(class_sim, id_sim)
        elif target_classes:
            final_class_id = class_sim
        elif target_id:
            final_class_id = id_sim
        else:
            final_class_id = 0.0

        return final_class_id, f"class_sim={class_sim:.2f}, id_sim={id_sim:.2f}"

    def _generate_resilient_selector(
        self,
        candidate: Tag,
        soup: BeautifulSoup,
        broken_selector: str,
        parsed: dict[str, Any],
        details: dict[str, Any],
    ) -> str:
        """Construct the cleanest, most resilient unique CSS selector."""
        def is_unique(sel: str) -> bool:
            try:
                matches = soup.select(sel)
                return len(matches) == 1 and matches[0] is candidate
            except Exception:
                return False

        # 1. Check data-testid
        for attr in ("data-testid", "data-test", "data-cy"):
            val = candidate.get(attr)
            if val:
                sel = f'[{attr}="{val}"]'
                if is_unique(sel):
                    return sel

        # 2. Check if broken selector was class-only (e.g. .btn-old -> .btn-primary-new)
        is_class_only = broken_selector.startswith(".") and not any(
            ch in broken_selector for ch in ("#", "[", " ", ">")
        )
        elem_classes = candidate.get("class", [])
        if isinstance(elem_classes, str):
            elem_classes = [elem_classes]

        if is_class_only and elem_classes:
            for c in elem_classes:
                sel = f".{c}"
                if is_unique(sel):
                    return sel
            full_class_sel = "." + ".".join(elem_classes)
            if is_unique(full_class_sel):
                return full_class_sel

        # 3. Check placeholder if input
        placeholder = candidate.get("placeholder")
        if placeholder:
            sel = f'{candidate.name}[placeholder="{placeholder}"]'
            if is_unique(sel):
                return sel
            sel_attr = f'[placeholder="{placeholder}"]'
            if is_unique(sel_attr):
                return sel_attr

        # 4. Check aria-label
        aria = candidate.get("aria-label")
        if aria:
            sel = f'{candidate.name}[aria-label="{aria}"]'
            if is_unique(sel):
                return sel
            sel_attr = f'[aria-label="{aria}"]'
            if is_unique(sel_attr):
                return sel_attr

        # 5. Check ID
        elem_id = candidate.get("id")
        if elem_id:
            sel = f"#{elem_id}"
            if is_unique(sel):
                return sel

        # 6. Check unique class combinations (with tag)
        if elem_classes:
            for c in elem_classes:
                sel = f".{c}"
                if is_unique(sel):
                    return sel
                sel_tag = f"{candidate.name}.{c}"
                if is_unique(sel_tag):
                    return sel_tag
            compound_tag_sel = f"{candidate.name}." + ".".join(elem_classes)
            if is_unique(compound_tag_sel):
                return compound_tag_sel

        # 7. Check name attribute
        name_attr = candidate.get("name")
        if name_attr:
            sel = f'{candidate.name}[name="{name_attr}"]'
            if is_unique(sel):
                return sel

        # 8. Check parent hierarchy
        parent = candidate.parent
        if parent and parent.name and parent.name not in ("[document]", "html", "body"):
            if parent.get("id"):
                sel = f"#{parent['id']} > {candidate.name}"
                if is_unique(sel):
                    return sel
            parent_classes = parent.get("class", [])
            if isinstance(parent_classes, str):
                parent_classes = [parent_classes]
            if parent_classes:
                sel = f".{parent_classes[0]} > {candidate.name}"
                if is_unique(sel):
                    return sel

        # 9. Fallback: tag and index
        if candidate.parent:
            siblings = [
                s for s in candidate.parent.find_all(candidate.name, recursive=False)
            ]
            if len(siblings) > 1:
                idx = siblings.index(candidate) + 1
                return f"{candidate.name}:nth-of-type({idx})"

        return candidate.name
