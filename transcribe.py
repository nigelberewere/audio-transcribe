import argparse
import logging
from pathlib import Path
from uuid import uuid4

from app.config import Settings
from app.db import Database
from app.worker import TranscriptionWorker


def main() -> None:
    parser = argparse.ArgumentParser(description="Zingsa Files Center meeting transcription")
    parser.add_argument("file")
    parser.add_argument("--model", default="auto", choices=["auto", "large-v3", "medium", "small", "tiny"])
    parser.add_argument("--format", default="txt", help="Comma-separated: txt,txt_timestamps,srt,vtt,docx,json")
    parser.add_argument("--language", default="auto")
    parser.add_argument("--initial-prompt", default="")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    settings = Settings(); settings.ensure_directories()
    database = Database(settings.db_path)
    job_id = uuid4().hex
    source = Path(args.file).resolve()
    database.create_job({"id": job_id, "filename": source.name, "source_path": str(source), "requested_model": args.model, "language": args.language, "initial_prompt": args.initial_prompt, "formats": [item.strip() for item in args.format.split(",")]})
    worker = TranscriptionWorker(settings, database)
    worker.process(database.get_job(job_id))
    print(f"Completed job {job_id} using {database.get_job(job_id)['selected_model']}")


if __name__ == "__main__":
    main()
