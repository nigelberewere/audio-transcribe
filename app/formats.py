import json
from datetime import datetime
from pathlib import Path


def timestamp(seconds: float) -> str:
    total = max(0, int(seconds))
    return f"{total // 3600:02}:{total % 3600 // 60:02}:{total % 60:02}"


def write_outputs(job: dict, segments: list[dict], output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(job["filename"]).stem
    paths = []
    plain = "\n\n".join(segment["text"].strip() for segment in segments if segment["text"].strip())
    timed = "\n\n".join(f"[{timestamp(segment['start'])}] {segment['text'].strip()}" for segment in segments if segment["text"].strip())
    if "txt" in job["formats"]:
        path = output_dir / f"{stem}.txt"; path.write_text(plain, encoding="utf-8"); paths.append(path)
    if "txt_timestamps" in job["formats"]:
        path = output_dir / f"{stem}_timestamps.txt"; path.write_text(timed, encoding="utf-8"); paths.append(path)
    if "srt" in job["formats"]:
        body = "\n\n".join(f"{index}\n{timestamp(segment['start'])},000 --> {timestamp(segment['end'])},000\n{segment['text'].strip()}" for index, segment in enumerate(segments, 1))
        path = output_dir / f"{stem}.srt"; path.write_text(body, encoding="utf-8"); paths.append(path)
    if "vtt" in job["formats"]:
        body = "WEBVTT\n\n" + "\n\n".join(f"{timestamp(segment['start'])}.000 --> {timestamp(segment['end'])}.000\n{segment['text'].strip()}" for segment in segments)
        path = output_dir / f"{stem}.vtt"; path.write_text(body, encoding="utf-8"); paths.append(path)
    if "json" in job["formats"]:
        path = output_dir / f"{stem}.json"; path.write_text(json.dumps({"job_id": job["id"], "filename": job["filename"], "model": job["selected_model"], "segments": segments}, indent=2), encoding="utf-8"); paths.append(path)
    if "docx" in job["formats"]:
        from docx import Document
        document = Document(); document.add_heading(job["filename"], 0)
        document.add_paragraph(f"Created: {datetime.now().isoformat()} | Model: {job['selected_model']}")
        for segment in segments:
            document.add_paragraph(f"[{timestamp(segment['start'])}] {segment['text'].strip()}")
        path = output_dir / f"{stem}.docx"; document.save(path); paths.append(path)
    return paths
