"""Local-first, zero-cloud visual regression checks for Hermes Unlimited A2UI.

Requires Playwright + a local Chromium binary. Baselines are never accepted
implicitly; updating them requires HERMES_VISUAL_UPDATE=1.
"""
import functools
import http.server
import os
from pathlib import Path
import shutil
import tempfile
import threading
import unittest

from unlimited.a2ui_adapter import company_surface
from unlimited.runtime import ProviderStore

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

ROOT = Path(__file__).resolve().parents[1]
BASELINES = ROOT / "tests" / "visual_baselines"
VIEWPORTS = {"mobile": (390, 844), "tablet": (820, 1180), "desktop": (1440, 900)}


def compare_png(actual: bytes, expected: bytes) -> bool:
    """Strict binary snapshot comparison; no remote API or AI judgment."""
    return actual == expected


class A2UIVisualRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if sync_playwright is None or not shutil.which("chromium"):
            raise unittest.SkipTest("Local Playwright and Chromium required")
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(
            executable_path=shutil.which("chromium"),
            headless=True, args=["--no-sandbox"],
        )
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(ROOT))
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)

    def test_visual_company_surface(self):
        update = os.environ.get("HERMES_VISUAL_UPDATE") == "1"
        strict = os.environ.get("HERMES_VISUAL_STRICT") == "1"
        artifact_dir = Path(os.environ.get("HERMES_VISUAL_ARTIFACTS", tempfile.gettempdir())) / "hermes-visual-qc"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as temp:
            store = ProviderStore(
                Path(temp) / "db.sqlite",
                lambda p, t, i: p == "provider1" and t == "tenant1" and i == "valid",
            )
            store.create_company("provider1", "tenant1", "acme", "Synthetic company", "valid")
            msg = company_surface(store, "provider1", "tenant1", "valid", surface_id="visual1")
            import json
            for viewport, (width, height) in VIEWPORTS.items():
                with self.subTest(viewport=viewport):
                    page = self.browser.new_page(
                        viewport={"width": width, "height": height},
                        device_scale_factor=1, reduced_motion="reduce",
                    )
                    try:
                        page.goto(f"http://127.0.0.1:{self.server.server_port}/web/a2ui/")
                        page.locator("#payload").fill(json.dumps(msg))
                        page.get_by_role("button", name="Render surface").click()
                        page.locator("#surface h2").wait_for()
                        page.evaluate("""() => {
                            document.documentElement.style.scrollBehavior = 'auto';
                            const s = document.createElement('style');
                            s.textContent = '* { animation: none !important; transition: none !important; caret-color: transparent !important; }';
                            document.head.appendChild(s);
                        }""")
                        image = page.locator("#surface").screenshot(animations="disabled")
                        baseline = BASELINES / f"a2ui-companies-{viewport}.png"
                        if update:
                            baseline.parent.mkdir(parents=True, exist_ok=True)
                            baseline.write_bytes(image)
                        elif not baseline.exists():
                            if strict:
                                self.fail(f"Missing visual baseline: {baseline}. Set HERMES_VISUAL_UPDATE=1 to capture reviewed baselines.")
                            (artifact_dir / f"a2ui-companies-{viewport}-actual.png").write_bytes(image)
                        elif not compare_png(image, baseline.read_bytes()):
                            actual = artifact_dir / f"a2ui-companies-{viewport}-actual.png"
                            actual.write_bytes(image)
                            self.fail(f"Visual regression at {viewport}; actual: {actual}; baseline: {baseline}")
                        # Negative control: a real CSS change must be detected.
                        page.locator("#surface").evaluate("""el => { el.style.border = "8px solid red"; }""")
                        changed = page.locator("#surface").screenshot(animations="disabled")
                        self.assertFalse(compare_png(changed, baseline.read_bytes()),
                                         f"Visual regression detector missed deliberate CSS change: {viewport}")
                    finally:
                        page.close()


if __name__ == "__main__":
    unittest.main()
