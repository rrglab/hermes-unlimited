"""Local-first, zero-cloud visual regression checks for Hermes Unlimited A2UI.

Requires Playwright + a local Chromium binary. Baselines are never accepted
implicitly; updating them requires HERMES_VISUAL_UPDATE=1.
"""
import functools
import http.server
import io
import os
import shutil
import tempfile
import threading
import unittest
from pathlib import Path

from unlimited.a2ui_adapter import company_surface
from unlimited.runtime import ProviderStore

try:
    from PIL import Image
except ImportError:
    Image = None

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

ROOT = Path(__file__).resolve().parents[1]
BASELINES = ROOT / "tests" / "visual_baselines"
VIEWPORTS = {"mobile": (390, 844), "tablet": (820, 1180), "desktop": (1440, 900)}


def compare_png(actual: bytes, expected: bytes) -> bool:
    """Compare PNGs with tight anti-aliasing tolerance; catches any real visual/CSS change."""
    if actual == expected:
        return True
    if Image is None:
        return False
    with Image.open(io.BytesIO(actual)) as a_img, Image.open(io.BytesIO(expected)) as e_img:
        a_rgb = a_img.convert("RGB")
        e_rgb = e_img.convert("RGB")
        if a_rgb.size != e_rgb.size:
            return False
        a_bytes = a_rgb.tobytes()
        e_bytes = e_rgb.tobytes()
        if a_bytes == e_bytes:
            return True
        total_channels = len(a_bytes)
        diffs = [abs(x - y) for x, y in zip(a_bytes, e_bytes)]
        # Allow minor cross-platform Chromium font/border anti-aliasing (<=24/255, mean <=1.0)
        # while strictly failing on any color, layout, border, or text regression.
        return max(diffs) <= 24 and (sum(diffs) / total_channels) <= 1.0


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
                            self.fail(f"Missing visual baseline: {baseline}. Explicitly set HERMES_VISUAL_UPDATE=1 to capture baselines.")
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
