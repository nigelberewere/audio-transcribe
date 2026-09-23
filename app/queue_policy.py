from dataclasses import dataclass


@dataclass(frozen=True)
class QueuePolicy:
    default_model: str = "large-v3"
    fallback_model: str = "medium"
    threshold: int = 2

    def choose_model(self, override: str | None, waiting_jobs: int) -> str:
        if override and override != "auto":
            return override
        if waiting_jobs >= self.threshold:
            return self.fallback_model
        return self.default_model
