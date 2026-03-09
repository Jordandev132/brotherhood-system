"""Post-recording video verification — ffmpeg frame extraction + tesseract OCR.

After the compositor creates the final MP4, this module:
1. Extracts a frame at each cue timestamp (+ response delay)
2. OCRs each frame with tesseract
3. Checks for expected chat text
4. Returns pass/fail with detailed breakdown

Jordan never reviews a video manually again.
"""
from __future__ import annotations

import logging
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

try:
    from PIL import Image
    import pytesseract
except ImportError as e:
    raise ImportError(
        "video_verifier requires: pip install pytesseract Pillow\n"
        "Also: brew install tesseract"
    ) from e

from viper.demos.voiceover import CuePoint

log = logging.getLogger(__name__)

# Seconds to wait after cue fires before extracting frame
# (gives chatbot time to respond visually)
_RESPONSE_DELAY = 4.0


@dataclass
class FrameCheck:
    """One frame verification check."""
    cue_action: str
    timestamp: float
    expected_texts: list[str]
    found_texts: list[str] = field(default_factory=list)
    missing_texts: list[str] = field(default_factory=list)
    ocr_text: str = ""
    passed: bool = False


@dataclass
class VideoVerifyResult:
    """Full video verification result."""
    passed: bool
    checks: list[FrameCheck]
    failures: list[str] = field(default_factory=list)

    def summary(self) -> str:
        passed_count = sum(1 for c in self.checks if c.passed)
        total = len(self.checks)
        if self.passed:
            return f"VIDEO VERIFY PASS ({passed_count}/{total} frames)"
        return (
            f"VIDEO VERIFY FAIL ({passed_count}/{total} frames) — "
            + "; ".join(self.failures)
        )


# Expected text per action — what should be visible in the frame
# after the cue fires and the chatbot responds
DENTAL_FRAME_CHECKS: list[dict] = [
    {
        "after_action": "open_chat",
        "expect": ["help"],
    },
    {
        "after_action": "type_insurance",
        "expect": ["Delta Dental", "insurance"],
    },
    {
        "after_action": "type_booking",
        "expect": ["appointment", "book"],
    },
    {
        "after_action": "type_hours",
        "expect": ["Saturday"],
    },
    {
        "after_action": "type_doctor_question",
        "expect": ["Dr."],
    },
    {
        "after_action": "submit",
        "expect": ["Thank"],
    },
]


def extract_frame(video_path: Path, timestamp: float, output_path: Path) -> bool:
    """Extract a single frame from video at given timestamp using ffmpeg."""
    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{timestamp:.2f}",
        "-i", str(video_path),
        "-frames:v", "1",
        "-q:v", "2",
        str(output_path),
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=15,
        )
        return output_path.exists() and output_path.stat().st_size > 0
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        log.warning("ffmpeg frame extraction failed: %s", e)
        return False


def ocr_frame(image_path: Path) -> str:
    """OCR a frame image and return extracted text."""
    try:
        img = Image.open(image_path)
        text = pytesseract.image_to_string(img, config="--psm 6")
        return text.strip()
    except Exception as e:
        log.warning("OCR failed for %s: %s", image_path, e)
        return ""


def verify_video(
    video_path: Path,
    cue_sheet: list[CuePoint],
    frame_checks: list[dict] | None = None,
    response_delay: float = _RESPONSE_DELAY,
) -> VideoVerifyResult:
    """Verify a composited video by extracting frames and OCRing them.

    For each cue in the cue sheet that has a matching frame check,
    extracts a frame at (cue.timestamp + response_delay), OCRs it,
    and checks for expected text.
    """
    if frame_checks is None:
        frame_checks = DENTAL_FRAME_CHECKS

    # Build lookup: action -> expected texts
    check_map = {c["after_action"]: c["expect"] for c in frame_checks}

    checks: list[FrameCheck] = []
    failures: list[str] = []

    with tempfile.TemporaryDirectory(prefix="viper_verify_") as tmp:
        tmp_dir = Path(tmp)

        for cue in cue_sheet:
            expected = check_map.get(cue.action)
            if expected is None:
                continue

            ts = cue.timestamp + response_delay
            frame_path = tmp_dir / f"frame_{cue.action}.png"

            fc = FrameCheck(
                cue_action=cue.action,
                timestamp=ts,
                expected_texts=expected,
            )

            # Extract frame
            if not extract_frame(video_path, ts, frame_path):
                fc.missing_texts = expected
                failures.append(f"frame extraction failed at {ts:.1f}s ({cue.action})")
                checks.append(fc)
                continue

            # OCR
            ocr_text = ocr_frame(frame_path)
            fc.ocr_text = ocr_text
            ocr_lower = ocr_text.lower()

            # Check expected texts
            for txt in expected:
                if txt.lower() in ocr_lower:
                    fc.found_texts.append(txt)
                else:
                    fc.missing_texts.append(txt)

            if fc.missing_texts:
                failures.append(
                    f"after '{cue.action}' @ {ts:.1f}s: missing {fc.missing_texts}"
                )
            else:
                fc.passed = True

            checks.append(fc)
            log.debug(
                "Frame %s @ %.1fs: found=%s missing=%s",
                cue.action, ts, fc.found_texts, fc.missing_texts,
            )

    return VideoVerifyResult(
        passed=len(failures) == 0,
        checks=checks,
        failures=failures,
    )
