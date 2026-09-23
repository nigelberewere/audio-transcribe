from faster_whisper import WhisperModel
from app.config import Settings

settings = Settings(); settings.ensure_directories()
for name in (settings.default_model, settings.fallback_model):
    print(f"Caching {name}...")
    WhisperModel(name, device="cpu", compute_type="int8", cpu_threads=1, download_root=str(settings.model_dir))
print("Model cache complete.")
