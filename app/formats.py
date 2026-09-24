import json
from datetime import datetime
from pathlib import Path
from typing import Any


def format_timestamp(seconds: float, fmt: str = "display") -> str:
    total_msec = int(round(seconds * 1000))
    hours = total_msec // 3_600_000
    minutes = (total_msec % 3_600_000) // 60_000
    secs = (total_msec % 60_000) // 1000
    msec = total_msec % 1000
    if fmt == "srt":
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{msec:03d}"
    elif fmt == "vtt":
        return f"{hours:02d}:{minutes:02d}:{secs:02d}.{msec:03d}"
    else:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def timestamp(seconds: float, fmt: str = "display") -> str:
    """Backward-compatible alias for callers using the old formatter name."""
    return format_timestamp(seconds, fmt)


def group_segments_into_paragraphs(
    segments: list[dict], pause_threshold: float = 2.0
) -> list[dict]:
    """Merge consecutive segments until a long pause or speaker change."""
    paragraphs: list[dict] = []
    current: dict[str, Any] | None = None
    has_speakers = _has_speakers(segments)
    for segment in segments:
        text = segment.get("text", "").strip()
        if not text:
            continue
        start = float(segment.get("start", 0.0))
        end = float(segment.get("end", start))
        speaker = segment.get("speaker")
        can_merge = (
            current is not None
            and start - current["end"] <= pause_threshold
            and (not has_speakers or speaker == current["speaker"])
        )
        if can_merge:
            current["texts"].append(text)
            current["end"] = end
        else:
            if current is not None:
                paragraphs.append({**current, "text": " ".join(current.pop("texts")).strip()})
            current = {"start": start, "end": end, "speaker": speaker, "texts": [text]}
    if current is not None:
        paragraphs.append({**current, "text": " ".join(current.pop("texts")).strip()})
    return paragraphs


def _has_speakers(segments: list[dict]) -> bool:
    return any(segment.get("speaker") for segment in segments)


def _display_text(paragraph: dict, has_speakers: bool) -> str:
    prefix = f"{paragraph['speaker']}: " if has_speakers and paragraph.get("speaker") else ""
    return f"{prefix}{paragraph['text']}"


def write_outputs(job: dict, segments: list[dict], output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(job["filename"]).stem
    paths = []
    paragraphs = group_segments_into_paragraphs(segments)
    has_speakers = _has_speakers(segments)
    plain = "\n\n".join(_display_text(paragraph, has_speakers) for paragraph in paragraphs)
    timed = "\n\n".join(f"[{format_timestamp(paragraph['start'])}] {_display_text(paragraph, has_speakers)}" for paragraph in paragraphs)
    if "txt" in job["formats"]:
        path = output_dir / f"{stem}.txt"; path.write_text(plain + "\n", encoding="utf-8"); paths.append(path)
    if "txt_timestamps" in job["formats"]:
        path = output_dir / f"{stem}_timestamps.txt"; path.write_text(timed + "\n", encoding="utf-8"); paths.append(path)
    if "srt" in job["formats"]:
        body = "\n\n".join(f"{index}\n{format_timestamp(segment.get('start', 0), 'srt')} --> {format_timestamp(segment.get('end', 0), 'srt')}\n{_display_text(segment, has_speakers)}" for index, segment in enumerate(segments, 1) if segment.get("text", "").strip())
        path = output_dir / f"{stem}.srt"; path.write_text(body, encoding="utf-8"); paths.append(path)
    if "vtt" in job["formats"]:
        body = "WEBVTT\n\n" + "\n\n".join(f"{format_timestamp(segment.get('start', 0), 'vtt')} --> {format_timestamp(segment.get('end', 0), 'vtt')}\n{_display_text(segment, has_speakers)}" for segment in segments if segment.get("text", "").strip())
        path = output_dir / f"{stem}.vtt"; path.write_text(body, encoding="utf-8"); paths.append(path)
    if "json" in job["formats"]:
        path = output_dir / f"{stem}.json"; path.write_text(json.dumps({"job_id": job["id"], "filename": job["filename"], "model": job["selected_model"], "segments": segments}, indent=2), encoding="utf-8"); paths.append(path)
    if "docx" in job["formats"]:
        from docx import Document
        from docx.shared import RGBColor
        document = Document(); document.add_heading(job["filename"], 0)
        metadata = [
            ("Filename", job["filename"]),
            ("Date processed", job.get("processed_at", job.get("completed_at", job.get("created_at", datetime.now().isoformat())))),
            ("Audio duration", format_timestamp(job.get("duration", 0.0))),
            ("Model used", job.get("selected_model", "unknown")),
            ("Device / compute type", f"{job.get('device', 'cpu')} / {job.get('compute_type', 'int8')}"),
            ("Detected language", job.get("detected_language", job.get("language", "auto"))),
            ("Total segment count", str(len(segments))),
        ]
        table = document.add_table(rows=0, cols=2)
        table.style = "Table Grid"
        for label, value in metadata:
            cells = table.add_row().cells
            cells[0].text = label
            cells[1].text = str(value)
        document.add_paragraph()
        for paragraph in paragraphs:
            para = document.add_paragraph()
            timestamp_run = para.add_run(f"[{format_timestamp(paragraph['start'])}] ")
            timestamp_run.font.color.rgb = RGBColor(100, 116, 139)
            if has_speakers and paragraph.get("speaker"):
                speaker_run = para.add_run(f"{paragraph['speaker']}: ")
                speaker_run.bold = True
                speaker_run.font.color.rgb = RGBColor(30, 58, 138)
            para.add_run(paragraph["text"])
        path = output_dir / f"{stem}.docx"; document.save(path); paths.append(path)
    return paths
