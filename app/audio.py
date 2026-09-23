import shutil
import subprocess
from pathlib import Path

SUPPORTED_EXTENSIONS = {".mp3", ".wav", ".m4a", ".mp4", ".mkv", ".ogg", ".flac", ".webm"}


def check_ffmpeg(path: str) -> None:
    if shutil.which(path) is None and not Path(path).exists():
        raise RuntimeError(f"ffmpeg was not found at '{path}'. Install it or set TRANSCRIBE_FFMPEG to ffmpeg.exe.")


def convert_to_wav(ffmpeg: str, source: Path, destination: Path) -> None:
    command = [ffmpeg, "-y", "-i", str(source), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(destination)]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"ffmpeg conversion failed: {result.stderr[-1000:]}")
