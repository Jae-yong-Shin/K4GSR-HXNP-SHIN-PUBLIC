"""Playwright E2E test fixtures for K4GSR Beamline UI.

Loads the bundle HTML via file:// (standalone mode, no server needed).
"""
import os
import pytest

# Bundle HTML path
_PROJECT_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(__file__), '..', '..'))
BUNDLE_HTML = os.path.join(
    _PROJECT_ROOT, 'virtual_beamline_nanoprobe_V4_36_bundle.html')


@pytest.fixture(scope="session")
def browser_context_args():
    """Override default Playwright context args."""
    return {
        "viewport": {"width": 1920, "height": 1080},
        "ignore_https_errors": True,
    }


@pytest.fixture(scope="session")
def bundle_url():
    """File URL to the bundle HTML."""
    if not os.path.isfile(BUNDLE_HTML):
        pytest.skip(f"Bundle not found: {BUNDLE_HTML}")
    # Convert Windows path to file:// URL
    path = BUNDLE_HTML.replace("\\", "/")
    if not path.startswith("/"):
        path = "/" + path
    return f"file://{path}"


@pytest.fixture
def page(browser_context_args, bundle_url):
    """Provide a fresh Playwright page loaded with the beamline UI."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(**browser_context_args)
        pg = context.new_page()
        # Suppress console errors from missing WebSocket server
        pg.on("pageerror", lambda e: None)
        pg.goto(bundle_url, wait_until="networkidle", timeout=30000)
        yield pg
        context.close()
        browser.close()
