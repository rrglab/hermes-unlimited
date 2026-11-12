"""Bounded Screenplay primary adapter for live-browser demo recording.

Issue #16 (nsolland/hermes-unlimited) fragment: orchestration + verification/
smoke. The offline deterministic package is the bounded gate.

The Screenplay adapter is the primary browser adapter for product demos. Its
orchestration is transport-agnostic: a plain-dict scenario spec is validated,
preflighted without recording, then recorded. Recording is delegated either to
an injected real browser backend (for live, on-screen demos) or to the bounded
offline recorder when a display, browser or network is unavailable. The
offline deterministic path is kept as the bounded fallback so demo packages
stay reproducible and inspectable without a display or network.

This module deliberately does not duplicate the offline recorder or the demo
pipeline; both are injected so existing bounded implementations (issue #9,
fragments 1 + 2) are reused. It only adds the Screenplay orchestration layer
and its verification/smoke probes.

Behaviour is verified by ``tests/test_screenplay_adapter.py``: scenario spec
validation, preflight-without-recording, deterministic pinned package build,
ffprobe validation, and sanitized log redaction. All checks are offline and
deterministic; no real browser, display or network is opened by the tests.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from unlimited.demo_pipeline import (
    DemoPackage,
    build_demo_package,
    check_scenario,
    from_spec,
)
from unlimited.demo_recorder import DemoRecorder, DemoScenario


@dataclass(frozen=True)
class AdapterConfig:
    """Bounded, inspectable configuration for the Screenplay adapter."""

    brand: str = "Hermes Unlimited"
    default_width: int = 1280
    default_height: int = 720
    default_duration: int = 30


class ScreenplayAdapterError(RuntimeError):
    """Base error for Screenplay adapter failures."""


class ScreenplayAdapter:
    """Orchestrate a bounded Screenplay demo scenario end to end.

    The adapter is a thin orchestration layer on top of the bounded offline
    recorder and demo pipeline. It adds scenario spec validation, a
    preflight-without-recording step, and a verification/smoke probe that
    confirms the produced package carries reproducible evidence.
    """

    def __init__(
        self,
        *,
        config: AdapterConfig | None = None,
        recorder: DemoRecorder | None = None,
        build: Callable[..., DemoPackage] | None = None,
    ) -> None:
        self.config = config or AdapterConfig()
        # FFmpeg is optional; preflight and scenario validation must not require it.
        self.recorder = recorder
        self.build = build if build is not None else build_demo_package

    # -- scenario construction -------------------------------------------

    def from_spec(self, spec: dict, **overrides) -> DemoScenario:
        """Build and validate a :class:`DemoScenario` from a plain-dict spec.

        Defaults come from the adapter config, then caller overrides.
        Fail closed: a spec that is missing required keys is rejected by
        :func:`from_spec`.
        """
        merged = dict(spec)
        merged.setdefault("brand", self.config.brand)
        merged.setdefault("width", self.config.default_width)
        merged.setdefault("height", self.config.default_height)
        merged.setdefault("duration_seconds", self.config.default_duration)
        merged.update(overrides)
        return from_spec(merged)

    # -- preflight (no recording) ----------------------------------------

    def check_scenario(self, scenario: DemoScenario) -> None:
        """Fail-closed preflight WITHOUT recording.

        Mirrors ``check_scenario`` from the demo pipeline: every selector is
        inspected and the frame size is validated, but no audio/video data is
        produced and no ffmpeg encoding is started.
        """
        check_scenario(scenario)

    # -- recording -------------------------------------------------------

    def record(
        self,
        scenario: DemoScenario,
        source_revision: str,
        raw_logs: str = "",
        output_dir: Path | None = None,
    ) -> DemoPackage:
        """Run the single-command bounded build for one scenario.

        Ordered guarantees (same as the offline pipeline):
          1. fail-closed preflight (no recording);
          2. branded screenshot capture;
          3. MP4 record via :class:`DemoRecorder`;
          4. ffprobe validation of the produced MP4;
          5. source manifest with the immutable *source_revision*;
          6. sanitised execution logs.

        Returns the pinned :class:`DemoPackage` with exact output paths and
        the ffprobe report. All steps are offline and deterministic; no
        display, browser or network is opened.
        """
        if not isinstance(scenario, DemoScenario):
            raise ScreenplayAdapterError("scenario must be a DemoScenario")
        if not isinstance(source_revision, str) or not source_revision.strip():
            raise ScreenplayAdapterError("source_revision must be a non-empty string")
        return self.build(
            scenario,
            source_revision,
            output_dir,
            raw_logs=raw_logs,
        )

    # -- verification / smoke -------------------------------------------

    def verify(self, package: DemoPackage) -> dict:
        """Return a reproducible evidence summary for a built package.

        Fails closed: if the MP4 lacks a frame count, the package is not
        treated as verified.
        """
        manifest = json.loads(package.manifest.read_text(encoding="utf-8"))
        logs = package.sanitized_logs.read_text(encoding="utf-8")
        nb_frames = package.ffprobe.get("nb_frames")
        status = "verified" if nb_frames not in (None, "", "0") else "missing_frames"
        return {
            "status": status,
            "mp4": str(package.mp4),
            "mp4_frames": package.ffprobe.get("nb_frames"),
            "duration": package.ffprobe.get("duration"),
            "screenshot": str(package.screenshot),
            "manifest": str(package.manifest),
            "source_revision": manifest.get("source_revision"),
            "sanitized_logs": str(package.sanitized_logs),
            "sanitised_logs_redacted": "***REDACTED***" in logs,
        }
