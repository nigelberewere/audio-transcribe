from app.formats import format_timestamp, group_segments_into_paragraphs, timestamp, write_outputs


def test_timestamp_is_hour_safe():
    assert timestamp(0) == "00:00:00"
    assert timestamp(3661.9) == "01:01:01"


def test_timestamp_preserves_milliseconds_for_subtitle_formats():
    assert format_timestamp(83.421, "srt") == "00:01:23,421"
    assert format_timestamp(83.421, "vtt") == "00:01:23.421"


def test_paragraphs_merge_until_pause():
    segments = [
        {"start": 0.0, "end": 1.0, "text": "First."},
        {"start": 1.5, "end": 2.0, "text": "Second."},
        {"start": 5.0, "end": 6.0, "text": "Third."},
    ]
    paragraphs = group_segments_into_paragraphs(segments)
    assert [paragraph["text"] for paragraph in paragraphs] == ["First. Second.", "Third."]


def test_paragraphs_split_when_speaker_changes():
    segments = [
        {"start": 0.0, "end": 1.0, "text": "One.", "speaker": "Speaker 1"},
        {"start": 1.2, "end": 2.0, "text": "Two.", "speaker": "Speaker 2"},
    ]
    paragraphs = group_segments_into_paragraphs(segments)
    assert len(paragraphs) == 2


def test_docx_contains_metadata_table(tmp_path):
    job = {
        "id": "job-1",
        "filename": "meeting.wav",
        "formats": ["docx"],
        "selected_model": "medium",
        "duration": 12.5,
        "device": "cpu",
        "compute_type": "int8",
        "detected_language": "en",
        "processed_at": "2026-09-23T12:00:00+00:00",
    }
    write_outputs(job, [{"start": 0.0, "end": 1.0, "text": "Hello."}], tmp_path)

    from docx import Document

    document = Document(tmp_path / "meeting.docx")
    rows = {(row.cells[0].text, row.cells[1].text) for row in document.tables[0].rows}
    assert ("Filename", "meeting.wav") in rows
    assert ("Date processed", "2026-09-23T12:00:00+00:00") in rows
    assert ("Total segment count", "1") in rows
