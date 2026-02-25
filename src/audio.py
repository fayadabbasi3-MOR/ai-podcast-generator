import logging
import subprocess
import tempfile
from pathlib import Path

from src.config import MP3_BITRATE, PAUSE_BETWEEN_SPEAKERS_MS

logger = logging.getLogger(__name__)


def generate_silence(duration_ms: int, output_path: Path) -> Path:
    """Generate a silent MP3 of the given duration using ffmpeg.

    Returns output_path.
    """
    duration_s = duration_ms / 1000
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", f"anullsrc=r=24000:cl=mono",
            "-t", str(duration_s),
            "-c:a", "libmp3lame",
            "-b:a", "128k",
            str(output_path),
        ],
        capture_output=True,
        check=True,
    )
    return output_path


def stitch_audio(
    segment_paths: list[Path],
    output_path: Path,
    pause_ms: int = PAUSE_BETWEEN_SPEAKERS_MS,
) -> Path:
    """Concatenate segment MP3s with silence gaps between speaker turns.

    Returns output_path.
    Raises subprocess.CalledProcessError on ffmpeg failure (hard fail).
    """
    tmp_dir = Path(tempfile.mkdtemp(prefix="stitch_"))

    # Generate silence file
    silence_path = tmp_dir / "silence.mp3"
    generate_silence(pause_ms, silence_path)

    # Build concat list
    concat_list_path = tmp_dir / "concat_list.txt"
    lines = []
    for i, seg_path in enumerate(segment_paths):
        lines.append(f"file '{seg_path}'")
        if i < len(segment_paths) - 1:
            lines.append(f"file '{silence_path}'")
    concat_list_path.write_text("\n".join(lines))

    # Run ffmpeg concat demuxer
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_list_path),
            "-c:a", "libmp3lame",
            "-b:a", "128k",
            str(output_path),
        ],
        capture_output=True,
        check=True,
    )

    return output_path


def get_mp3_duration_seconds(file_path: Path) -> float:
    """Calculate MP3 duration from file size and bitrate.

    Formula: (file_size_bytes * 8) / MP3_BITRATE
    """
    size_bytes = file_path.stat().st_size
    return (size_bytes * 8) / MP3_BITRATE


def format_duration_itunes(seconds: float) -> str:
    """Format seconds as HH:MM:SS for iTunes duration tag.

    Example: 485.7 -> "00:08:05"
    """
    total = int(seconds)
    hours = total // 3600
    minutes = (total % 3600) // 60
    secs = total % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"
