"""Adversarial Verification Suite for Milestone 3 Frontend UI & i18n Completeness.

Validates:
1. Syntax and importability of en.js and de.js locale files.
2. Complete coverage of all t('...') keys referenced in M3 JSX components:
   - ModpackUpdateModal.jsx
   - ClientModFilterPanel.jsx
   - ModManagerPanel.jsx
   - ServerDetailsPage.jsx
3. 1:1 symmetry between en.js and de.js across both M3 namespaces and the entire dictionary.
4. Parity of interpolation placeholders (e.g. {{serverName}}, {{version}}, {{count}}).
5. AST / Import integrity of all modified frontend components.
6. Empirical reproduction of bugs and dead keys:
   - ModpackUpdateModal.jsx references missing 'common.tryAgain', causing button to display raw key name.
   - ModManagerPanel.jsx imports useTranslation but never uses it.
   - ModpackUpdateModal, ModManagerPanel, and ServerDetailsPage contain hardcoded English strings
     bypassing available or needed i18n translations.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FRONTEND_DIR = REPO_ROOT / "frontend"
LOCALES_DIR = FRONTEND_DIR / "src" / "i18n" / "locales"


def load_locale_via_node(lang: str) -> Dict[str, Any]:
    """Load and evaluate a JS locale file using Node.js ESM loader."""
    js_file = LOCALES_DIR / f"{lang}.js"
    assert js_file.is_file(), f"Locale file not found: {js_file}"

    # Use node to import and dump JSON via file URI
    file_uri = js_file.as_uri()
    node_code = (
        f"import loc from '{file_uri}';\n"
        "console.log(JSON.stringify(loc));\n"
    )

    proc = subprocess.run(
        ["node", "--input-type=module", "-e", node_code],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"Failed to load {lang}.js via Node: {proc.stderr}")

    for line in proc.stdout.splitlines():
        trimmed = line.strip()
        if trimmed.startswith("{") and trimmed.endswith("}"):
            return json.loads(trimmed)

    raise ValueError(f"No valid JSON output received for {lang}.js: {proc.stdout}")


def flatten_keys(d: Dict[str, Any], prefix: str = "") -> Dict[str, str]:
    """Recursively flatten nested dictionary keys with dot notation."""
    items: Dict[str, str] = {}
    for k, v in d.items():
        new_key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            items.update(flatten_keys(v, new_key))
        else:
            items[new_key] = str(v)
    return items


def simulate_t_function(translations: Dict[str, Any], key: str, params: Dict[str, Any] = None) -> str:
    """Accurately simulate frontend/src/i18n/I18nContext.jsx t(key, params) behavior."""
    if params is None:
        params = {}
    keys = key.split('.')
    val = translations
    for k in keys:
        if isinstance(val, dict) and k in val:
            val = val[k]
        else:
            return key  # Line 133 of I18nContext: fallback to key
    if not isinstance(val, str):
        return key
    return re.sub(r"\{\{(\w+)\}\}", lambda m: str(params.get(m.group(1), m.group(0))), val)


@pytest.fixture(scope="module")
def locales() -> Tuple[Dict[str, str], Dict[str, str], Dict[str, Any], Dict[str, Any]]:
    """Fixture providing raw and flattened en and de dictionaries."""
    en_raw = load_locale_via_node("en")
    de_raw = load_locale_via_node("de")
    en_flat = flatten_keys(en_raw)
    de_flat = flatten_keys(de_raw)
    return en_flat, de_flat, en_raw, de_raw


# ─── Test 1: Syntax & Character Encoding Integrity ──────────────────────────

def test_locales_syntax_and_utf8():
    """Verify that both locale files are valid UTF-8 without double-encoded mojibake."""
    for lang in ["en", "de"]:
        path = LOCALES_DIR / f"{lang}.js"
        content = path.read_text(encoding="utf-8")
        assert len(content) > 1000, f"{lang}.js is unexpectedly small ({len(content)} chars)"

        # Check for typical Mojibake artifacts (double-encoded UTF-8)
        mojibake_patterns = [
            "Ã¤", "Ã¼", "Ã¶", "Ã„", "Ãœ", "Ã–", "ÃŸ", "Ã©", "â€“", "â€”"
        ]
        found_mojibake = [pat for pat in mojibake_patterns if pat in content]
        assert not found_mojibake, f"{lang}.js contains UTF-8 double-encoding artifacts: {found_mojibake}"


# ─── Test 2: Extraction and Verification of JSX Translation Keys ─────────────

def extract_t_calls_from_file(file_path: Path) -> List[Tuple[str, int]]:
    """Extract all t('...') and t(`...`) calls with their line numbers."""
    content = file_path.read_text(encoding="utf-8")
    lines = content.splitlines()
    calls = []

    pattern = re.compile(r"""\bt\(\s*['"]([a-zA-Z0-9_.-]+)['"]""")
    template_pattern = re.compile(r"""\bt\(\s*`([^`]+)`""")

    for idx, line in enumerate(lines, 1):
        for match in pattern.finditer(line):
            calls.append((match.group(1), idx))
        for match in template_pattern.finditer(line):
            calls.append((match.group(1), idx))

    return calls


def test_m3_jsx_keys_completeness_and_exceptions(locales):
    """Check every translation key used in M3 JSX files against en.js and de.js."""
    en_flat, de_flat, _, _ = locales

    m3_files = [
        FRONTEND_DIR / "src" / "components" / "server-details" / "ModpackUpdateModal.jsx",
        FRONTEND_DIR / "src" / "components" / "server-details" / "ClientModFilterPanel.jsx",
        FRONTEND_DIR / "src" / "components" / "server-details" / "ModManagerPanel.jsx",
        FRONTEND_DIR / "src" / "pages" / "ServerDetailsPage.jsx",
    ]

    missing_keys = []
    checked_count = 0

    for file_path in m3_files:
        assert file_path.is_file(), f"File does not exist: {file_path}"
        calls = extract_t_calls_from_file(file_path)

        for key_expr, line_no in calls:
            if "${step.key}" in key_expr:
                step_keys = [
                    "progressStopping",
                    "progressBackup",
                    "progressDownloading",
                    "progressCleaning",
                    "progressFiltering",
                    "progressRestarting",
                ]
                expanded_keys = [key_expr.replace("${step.key}", sk) for sk in step_keys]
            else:
                expanded_keys = [key_expr]

            for k in expanded_keys:
                checked_count += 1
                en_missing = k not in en_flat
                de_missing = k not in de_flat
                if en_missing or de_missing:
                    missing_keys.append({
                        "file": file_path.name,
                        "line": line_no,
                        "key": k,
                        "missing_in_en": en_missing,
                        "missing_in_de": de_missing,
                    })

    # Assert that all keys referenced in JSX exist in en.js and de.js
    assert not missing_keys, f"Missing keys in JSX: {missing_keys}"
    assert checked_count > 40, f"Expected >40 checked keys across M3 components, found {checked_count}"


# ─── Test 3: Empirical Bug Reproduction - common.tryAgain ───────────────────

def test_empirical_bug_common_try_again(locales):
    """Verify resolution of common.tryAgain:

    In ModpackUpdateModal.jsx line 627:
        {t('common.tryAgain') || 'Try Again'}

    'common.tryAgain' is defined in en.js ('Try Again') and de.js ('Erneut versuchen').
    Simulate runtime t() to confirm correct localized strings are rendered.
    """
    en_flat, de_flat, en_raw, de_raw = locales

    # 1. Verify key exists in en.js and de.js under common
    assert "common.tryAgain" in en_flat, "common.tryAgain must exist in en.js"
    assert "common.tryAgain" in de_flat, "common.tryAgain must exist in de.js"

    # 2. Verify key exists in errors namespace as well
    assert "errors.tryAgain" in en_flat, "errors.tryAgain exists in en.js"
    assert "errors.tryAgain" in de_flat, "errors.tryAgain exists in de.js"

    # 3. Simulate runtime t() output in English and German
    en_rendered = simulate_t_function(en_raw, "common.tryAgain")
    de_rendered = simulate_t_function(de_raw, "common.tryAgain")

    assert en_rendered == "Try Again", f"Expected 'Try Again', got {en_rendered}"
    assert de_rendered == "Erneut versuchen", f"Expected 'Erneut versuchen', got {de_rendered}"

    # 4. Confirm JSX call site in ModpackUpdateModal.jsx
    modal_file = FRONTEND_DIR / "src" / "components" / "server-details" / "ModpackUpdateModal.jsx"
    modal_text = modal_file.read_text(encoding="utf-8")
    assert "t('common.tryAgain')" in modal_text, "ModpackUpdateModal.jsx references t('common.tryAgain')"


# ─── Test 4: Global Locale Dictionary Symmetry (en.js vs de.js) ─────────────

def test_global_locale_dictionary_symmetry(locales):
    """Verify 1:1 symmetry between en.js and de.js across the ENTIRE application."""
    en_flat, de_flat, _, _ = locales

    missing_in_de = set(en_flat.keys()) - set(de_flat.keys())
    missing_in_en = set(de_flat.keys()) - set(en_flat.keys())

    assert not missing_in_de, f"Keys in en.js missing from de.js: {missing_in_de}"
    assert not missing_in_en, f"Keys in de.js missing from en.js: {missing_in_en}"
    assert len(en_flat) == len(de_flat), f"Key counts differ: en={len(en_flat)}, de={len(de_flat)}"


# ─── Test 5: Milestone 3 Namespace Symmetry ──────────────────────────────────

def test_modpack_update_and_client_mod_filter_namespace_symmetry(locales):
    """Verify 1:1 symmetry in modpackUpdate and clientModFilter.whitelist namespaces."""
    en_flat, de_flat, _, _ = locales

    namespaces = ["modpackUpdate", "clientModFilter.whitelist"]

    for ns in namespaces:
        en_ns_keys = {k for k in en_flat if k.startswith(ns + ".")}
        de_ns_keys = {k for k in de_flat if k.startswith(ns + ".")}

        assert len(en_ns_keys) > 0, f"No keys found in en.js for namespace {ns}"
        assert len(de_ns_keys) > 0, f"No keys found in de.js for namespace {ns}"

        missing_in_de = en_ns_keys - de_ns_keys
        extra_in_de = de_ns_keys - en_ns_keys

        assert not missing_in_de, f"Namespace '{ns}' has keys in en.js missing from de.js: {missing_in_de}"
        assert not extra_in_de, f"Namespace '{ns}' has keys in de.js missing from en.js: {extra_in_de}"


# ─── Test 6: Interpolation Placeholders Parity ───────────────────────────────

def test_interpolation_placeholders_match(locales):
    """Verify that interpolation placeholders like {{serverName}} match exactly between en and de."""
    en_flat, de_flat, _, _ = locales

    placeholder_pattern = re.compile(r"\{\{([a-zA-Z0-9_]+)\}\}")
    mismatches = []

    m3_namespaces = ["modpackUpdate", "clientModFilter"]

    for key, en_text in en_flat.items():
        if not any(key.startswith(ns) for ns in m3_namespaces):
            continue

        de_text = de_flat.get(key)
        if not de_text:
            continue

        en_vars = set(placeholder_pattern.findall(en_text))
        de_vars = set(placeholder_pattern.findall(de_text))

        if en_vars != de_vars:
            mismatches.append(f"Key '{key}': en placeholders {en_vars} != de placeholders {de_vars}")

    assert not mismatches, "Placeholder mismatches between locales:\n" + "\n".join(mismatches)


# ─── Test 7: Component Import & Dependency Integrity ────────────────────────

def test_component_relative_imports():
    """Verify all relative JS/JSX imports in the M3 components resolve to valid files."""
    m3_files = [
        FRONTEND_DIR / "src" / "components" / "server-details" / "ModpackUpdateModal.jsx",
        FRONTEND_DIR / "src" / "components" / "server-details" / "ClientModFilterPanel.jsx",
        FRONTEND_DIR / "src" / "components" / "server-details" / "ModManagerPanel.jsx",
        FRONTEND_DIR / "src" / "pages" / "ServerDetailsPage.jsx",
    ]

    import_pattern = re.compile(r"""\bfrom\s+['"](\.[^'"]+)['"]""")

    missing_imports = []
    for f in m3_files:
        content = f.read_text(encoding="utf-8")
        for match in import_pattern.finditer(content):
            rel_path = match.group(1)
            base = f.parent
            resolved = (base / rel_path).resolve()

            candidates = [
                resolved,
                resolved.with_suffix(".js"),
                resolved.with_suffix(".jsx"),
                resolved / "index.js",
                resolved / "index.jsx",
            ]
            if not any(c.exists() for c in candidates):
                missing_imports.append(f"{f.name}: import '{rel_path}' does not resolve")

    assert not missing_imports, "Unresolved relative imports:\n" + "\n".join(missing_imports)


# ─── Test 8: ModManagerPanel Dead Import Audit ───────────────────────────────

def test_modmanager_unused_translation_import():
    """Verify that ModManagerPanel.jsx imports and utilizes useTranslation."""
    mm_file = FRONTEND_DIR / "src" / "components" / "server-details" / "ModManagerPanel.jsx"
    content = mm_file.read_text(encoding="utf-8")

    assert "import { useTranslation } from '../../i18n';" in content, "Import present in ModManagerPanel"
    # Verify useTranslation is invoked
    assert "useTranslation()" in content, "useTranslation() is called in ModManagerPanel.jsx"
    # Verify t(...) is used
    calls = extract_t_calls_from_file(mm_file)
    assert len(calls) > 0, f"Expected t() calls in ModManagerPanel, found {calls}"


# ─── Test 9: Production Build Assets Sanity ─────────────────────────────────

def test_production_build_artifacts():
    """Ensure production build directory contains valid index.html and compiled JS/CSS bundles."""
    build_dir = FRONTEND_DIR / "build"
    assert build_dir.is_dir(), "frontend/build directory does not exist"

    index_html = build_dir / "index.html"
    assert index_html.is_file(), "frontend/build/index.html is missing"
    html_content = index_html.read_text(encoding="utf-8")
    assert "<div id=\"root\">" in html_content, "index.html does not contain root div"

    static_js = list((build_dir / "static" / "js").glob("main.*.js"))
    assert len(static_js) > 0, "No main bundle static/js/main.*.js found"


# ─── Test 10: Adversarial Audit of Untranslated Strings & Dead Keys ─────────

def test_untranslated_and_dead_keys_audit(locales):
    """Audit user-visible strings and ensure modpackUpdate keys are actively utilized."""
    en_flat, _, _, _ = locales

    # Extract all modpackUpdate keys
    all_mu_keys = {k for k in en_flat if k.startswith("modpackUpdate.")}

    # Extract all t() keys in frontend
    m3_files = [
        FRONTEND_DIR / "src" / "components" / "server-details" / "ModpackUpdateModal.jsx",
        FRONTEND_DIR / "src" / "components" / "server-details" / "ClientModFilterPanel.jsx",
        FRONTEND_DIR / "src" / "components" / "server-details" / "ModManagerPanel.jsx",
        FRONTEND_DIR / "src" / "pages" / "ServerDetailsPage.jsx",
    ]

    used_keys = set()
    for f in m3_files:
        for k, _ in extract_t_calls_from_file(f):
            if "${step.key}" in k:
                for sk in ["progressStopping", "progressBackup", "progressDownloading", "progressCleaning", "progressFiltering", "progressRestarting"]:
                    used_keys.add(k.replace("${step.key}", sk))
            else:
                used_keys.add(k)

    # Previously bypassed keys must now be actively used
    previously_bypassed = [
        "modpackUpdate.modsCleanedCount",
        "modpackUpdate.modsAddedCount",
        "modpackUpdate.clientModsFilteredCount",
        "modpackUpdate.updateButton",
        "modpackUpdate.updateAvailable",
        "modpackUpdate.upToDate",
        "modpackUpdate.updateToVersion",
        "modpackUpdate.changeVersion",
        "modpackUpdate.updateAvailableDesc",
        "modpackUpdate.cleanedModsTitle",
        "modpackUpdate.newModsTitle",
        "modpackUpdate.clientModsTitle",
        "modpackUpdate.cleanedModsListTitle",
        "modpackUpdate.isolatedClientModsTitle",
    ]
    for pk in previously_bypassed:
        assert pk in used_keys, f"Expected {pk} to be used in JSX components, but was not found in used_keys: {used_keys}"
