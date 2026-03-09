"""Compositor — Video + audio compositing for demo videos."""
from __future__ import annotations

from pathlib import Path

from moviepy import (
    AudioFileClip,
    ColorClip,
    CompositeVideoClip,
    TextClip,
    VideoFileClip,
)

# macOS system font paths
_FONT_BOLD = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
_FONT_REGULAR = "/System/Library/Fonts/Supplemental/Arial.ttf"


def composite_horizontal(
    video_path: Path,
    audio_path: Path,
    output_dir: Path,
) -> Path:
    """Composite horizontal (1920x1080) screen recording with voiceover."""
    output_dir.mkdir(parents=True, exist_ok=True)

    video = VideoFileClip(str(video_path))
    audio = AudioFileClip(str(audio_path))

    target_duration = audio.duration + 2.0
    if video.duration > target_duration:
        video = video.subclipped(0, target_duration)

    print("  [compositor] Exporting horizontal (1920x1080)...")
    final = video.with_audio(audio)
    h_path = output_dir / "dental_demo_horizontal.mp4"

    final.write_videofile(
        str(h_path),
        fps=30,
        codec="libx264",
        audio_codec="aac",
        preset="medium",
        ffmpeg_params=["-movflags", "+faststart"],
        logger=None,
    )

    video.close()
    audio.close()
    print(f"  [compositor] Horizontal: {h_path}")
    return h_path


def composite_vertical(
    video_path: Path,
    audio_path: Path,
    output_dir: Path,
    business_name: str,
) -> Path:
    """Composite vertical (1080x1920) from mobile recording.

    No header/footer overlays — the page's own branding is already visible
    in the mobile recording. Just scale to fill 1080x1920 cleanly.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    video = VideoFileClip(str(video_path))
    audio = AudioFileClip(str(audio_path))

    target_duration = audio.duration + 2.0
    if video.duration > target_duration:
        video = video.subclipped(0, target_duration)

    print("  [compositor] Exporting vertical (1080x1920)...")

    v_width = 1080
    total_h = 1920

    # Scale mobile recording to fill width
    scaled = video.resized(width=v_width)

    if scaled.h >= total_h:
        # Recording is taller than 1920 — crop from top to keep chat visible
        # (chat is the main content, hero header is less important)
        crop_top = scaled.h - total_h
        scaled = scaled.cropped(x1=0, y1=crop_top, x2=v_width, y2=scaled.h)
    else:
        # Recording is shorter — center vertically on black background
        bg = ColorClip(
            size=(v_width, total_h),
            color=(248, 250, 252),
        ).with_duration(scaled.duration)
        y_offset = (total_h - scaled.h) // 2
        scaled = CompositeVideoClip(
            [bg, scaled.with_position((0, y_offset))],
            size=(v_width, total_h),
        )

    final = scaled.with_audio(audio)
    v_path = output_dir / "dental_demo_vertical.mp4"

    final.write_videofile(
        str(v_path),
        fps=30,
        codec="libx264",
        audio_codec="aac",
        preset="medium",
        ffmpeg_params=["-movflags", "+faststart"],
        logger=None,
    )

    video.close()
    audio.close()
    print(f"  [compositor] Vertical: {v_path}")
    return v_path


def composite(
    video_path: Path,
    audio_path: Path,
    output_dir: Path,
    business_name: str,
    vertical_video_path: Path | None = None,
) -> tuple[Path, Path]:
    """Composite both horizontal and vertical demo videos.

    Args:
        video_path: desktop recording (1920x1080 WebM)
        audio_path: voiceover audio (WAV)
        output_dir: directory for output MP4 files
        business_name: name shown on vertical video header
        vertical_video_path: separate mobile recording (390x844 WebM)

    Returns:
        tuple of (horizontal_mp4_path, vertical_mp4_path)
    """
    h_path = composite_horizontal(video_path, audio_path, output_dir)
    v_source = vertical_video_path if vertical_video_path else video_path
    v_path = composite_vertical(v_source, audio_path, output_dir, business_name)
    return h_path, v_path
