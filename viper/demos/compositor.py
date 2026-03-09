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


def composite(
    video_path: Path,
    audio_path: Path,
    output_dir: Path,
    business_name: str,
) -> tuple[Path, Path]:
    """Composite screen recording with voiceover audio.

    Produces:
        1. Horizontal (1920x1080) — full screen recording with voiceover
        2. Vertical (1080x1920) — center-cropped with branded header/footer

    Args:
        video_path: path to screen recording (WebM)
        audio_path: path to voiceover audio (WAV)
        output_dir: directory for output MP4 files
        business_name: name shown on vertical video header

    Returns:
        tuple of (horizontal_mp4_path, vertical_mp4_path)
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load clips
    video = VideoFileClip(str(video_path))
    audio = AudioFileClip(str(audio_path))

    # Trim video to audio duration + 2s buffer
    target_duration = audio.duration + 2.0
    if video.duration > target_duration:
        video = video.subclipped(0, target_duration)

    # === Horizontal (1920x1080) ===
    print("  [compositor] Exporting horizontal (1920x1080)...")
    horizontal = video.with_audio(audio)
    h_path = output_dir / "dental_demo_horizontal.mp4"

    horizontal.write_videofile(
        str(h_path),
        fps=30,
        codec="libx264",
        audio_codec="aac",
        preset="medium",
        ffmpeg_params=["-movflags", "+faststart"],
        logger=None,
    )

    # === Vertical (1080x1920) ===
    print("  [compositor] Exporting vertical (1080x1920)...")

    # Crop center of horizontal video (focus on chat widget area — right side)
    # Chat widget is on the right side of the 1920px screen
    # Crop a 1080-wide strip from the right-center area
    v_width = 1080
    v_content_height = 1520  # Video content area (leaving room for header/footer)

    # Crop from right side where the chat widget lives
    crop_x = max(0, video.w - v_width - 50)  # 50px margin from right edge
    crop_y = 0
    cropped = video.cropped(
        x1=crop_x, y1=crop_y,
        x2=crop_x + v_width, y2=min(video.h, crop_y + v_content_height),
    )

    # Scale cropped video to fit content area
    scale_factor = v_width / cropped.w
    cropped = cropped.resized(width=v_width)

    # Header bar — branded with business name
    header_h = 200
    header_bg = ColorClip(
        size=(v_width, header_h),
        color=(37, 99, 235),  # Brand blue
    ).with_duration(cropped.duration)

    header_text = TextClip(
        text=business_name,
        font_size=48,
        color="white",
        font="Arial-Bold",
    ).with_duration(cropped.duration).with_position(("center", 70))

    subtitle_text = TextClip(
        text="AI Assistant Demo",
        font_size=28,
        color="rgba(255,255,255,0.8)",
        font="Arial",
    ).with_duration(cropped.duration).with_position(("center", 135))

    # Footer bar — CTA
    footer_h = 200
    footer_bg = ColorClip(
        size=(v_width, footer_h),
        color=(37, 99, 235),
    ).with_duration(cropped.duration)

    footer_text = TextClip(
        text="Get this for your business",
        font_size=36,
        color="white",
        font="Arial-Bold",
    ).with_duration(cropped.duration).with_position(("center", 80))

    # Compose vertical layout
    total_h = 1920
    content_y = header_h
    footer_y = total_h - footer_h

    # Background
    bg = ColorClip(
        size=(v_width, total_h),
        color=(248, 250, 252),  # Light bg
    ).with_duration(cropped.duration)

    vertical = CompositeVideoClip(
        [
            bg,
            header_bg.with_position((0, 0)),
            header_text,
            subtitle_text,
            cropped.with_position((0, content_y)),
            footer_bg.with_position((0, footer_y)),
            footer_text.with_position(("center", footer_y + 80)),
        ],
        size=(v_width, total_h),
    ).with_audio(audio)

    v_path = output_dir / "dental_demo_vertical.mp4"

    vertical.write_videofile(
        str(v_path),
        fps=30,
        codec="libx264",
        audio_codec="aac",
        preset="medium",
        ffmpeg_params=["-movflags", "+faststart"],
        logger=None,
    )

    # Cleanup
    video.close()
    audio.close()
    horizontal.close()

    print(f"  [compositor] Horizontal: {h_path}")
    print(f"  [compositor] Vertical: {v_path}")
    return h_path, v_path
