# Local visual QC (optional)

Run the existing A2UI functional browser tests first. This additional suite
captures three viewports (390×844, 820×1180, 1440×900) using **local**
Chromium and Playwright. It never uploads screenshots, calls cloud APIs,
creates GitHub Actions minutes, or accepts image differences automatically.

```bash
python -m pip install playwright
# Install your system Chromium (executable must be named chromium)
HERMES_VISUAL_UPDATE=1 python -m unittest tests.test_a2ui_visual
git add tests/visual_baselines
# Review all three generated PNG files before committing them.
python -m unittest tests.test_a2ui_visual
```

To run with a custom output directory, set `HERMES_VISUAL_ARTIFACTS`.
A visual mismatch writes the actual screenshot and fails the test. Missing
baselines also fail; they are not automatically created. Baseline updates
are opt-in and should be reviewed as code changes.

**Scope:** This checks one synthetic A2UI company view, not customer-facing
Captain's Bridge, accessibility, correctness of business logic, or every
device/browser. Exact PNG bytes are compared: environment/font/browser
differences can produce false positives. Pin Chromium and fonts in your
local test environment. The existing functional browser tests remain the
primary behavioral checks.

**Optional UI Verify:** The external uiverify service can be integrated
later as an independent adapter, but is not a required dependency. Do not
send tenant content or private screenshots to external services by default.
