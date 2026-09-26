"""Speaker Diarization Module.
Provides optional speaker labeling (e.g., 'Speaker 1:', 'Speaker 2:')
using pyannote.audio or fallback speaker segmentation.
Works seamlessly offline if models are pre-cached, and fails gracefully
with clear instructions if unconfigured or toggled off.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

DIARIZATION_SETUP_INSTRUCTIONS = """
Speaker Diarization Setup Guide (Optional Feature):
1. Create a free account at https://huggingface.co
2. Accept user conditions for the following two models:
   - https://huggingface.co/pyannote/speaker-diarization-3.1
   - https://huggingface.co/pyannote/segmentation-3.0
3. Create an Access Token (Read permissions) at:
   https://huggingface.co/settings/tokens
4. Install pyannote.audio:
   pip install pyannote.audio
5. Provide your token in the Web UI, or set the environment variable:
   $env:HF_TOKEN = "your_huggingface_token"
   or pass --hf-token "your_token" in CLI.

When the 'Speaker Labels' toggle is OFF or token is omitted,
transcription proceeds normally without diarization.
"""


def is_diarization_available(hf_token: Optional[str] = None) -> Tuple[bool, str]:
    """Check if pyannote.audio is installed and whether a HuggingFace token is provided."""
    token = hf_token or os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN")
    try:
        import pyannote.audio  # noqa: F401
    except ImportError:
        return False, "pyannote.audio is not installed. Run: pip install pyannote.audio"

    if not token:
        return False, "HuggingFace token missing. Diarization requires an HF token to load the pyannote pipeline."

    return True, "Diarization pipeline available"


def _load_pipeline(token: str):
    import yaml
    from pyannote.audio import Pipeline

    # 1. Attempt direct load (pyannote 3.x or 4.x when community-1 is accessible)
    try:
        pipeline = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1", token=token)
        if pipeline is not None:
            return pipeline
    except TypeError:
        try:
            pipeline = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1", use_auth_token=token)
            if pipeline is not None:
                return pipeline
        except Exception:
            pass
    except Exception:
        pass

    # 2. Pyannote 4.x compatibility: provide DummyPLDA for AgglomerativeClustering to bypass gated community-1 PLDA requirement
    try:
        from huggingface_hub import hf_hub_download
        from pyannote.audio.core.plda import PLDA

        class _DummyPLDA(PLDA):
            def __init__(self):
                pass

        config_yml = hf_hub_download("pyannote/speaker-diarization-3.1", "config.yaml", token=token)
        with open(config_yml, "r", encoding="utf-8") as fp:
            config = yaml.load(fp, Loader=yaml.SafeLoader)

        if "pipeline" in config and "params" in config["pipeline"]:
            clustering = config["pipeline"]["params"].get("clustering")
            if clustering and clustering != "VBxClustering":
                config["pipeline"]["params"]["plda"] = _DummyPLDA()

        pipeline = Pipeline.from_pretrained(config, token=token)
        if pipeline is not None:
            return pipeline
    except Exception:
        pass

    # 3. Fallback: try community-1 directly
    try:
        pipeline = Pipeline.from_pretrained("pyannote/speaker-diarization-community-1", token=token)
        if pipeline is not None:
            return pipeline
    except Exception:
        pass

    raise RuntimeError(
        "Failed to initialize pyannote pipeline. Please verify your Hugging Face token and ensure you have accepted model conditions at https://huggingface.co/pyannote/speaker-diarization-3.1 and https://huggingface.co/pyannote/segmentation-3.0"
    )


def diarize_audio(
    wav_path: str | Path,
    hf_token: Optional[str] = None,
    num_speakers: Optional[int] = None,
    min_speakers: Optional[int] = None,
    max_speakers: Optional[int] = None,
) -> List[Tuple[float, float, str]]:
    """Perform speaker diarization on a 16kHz WAV file.

    Returns a list of (start_sec, end_sec, speaker_id) tuples.
    """
    token = hf_token or os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN")
    if not token:
        raise ValueError(
            f"Speaker diarization requires a HuggingFace token.\n{DIARIZATION_SETUP_INSTRUCTIONS}"
        )

    try:
        import torch

        pipeline = _load_pipeline(token)

        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        pipeline.to(device)

        params: Dict[str, Any] = {}
        if num_speakers is not None and num_speakers > 0:
            params["num_speakers"] = num_speakers
        if min_speakers is not None and min_speakers > 0:
            params["min_speakers"] = min_speakers
        if max_speakers is not None and max_speakers > 0:
            params["max_speakers"] = max_speakers

        diarization = pipeline(str(wav_path), **params)

        # Pyannote 4.x returns DiarizeOutput with exclusive_speaker_diarization/speaker_diarization
        annotation = getattr(
            diarization,
            "exclusive_speaker_diarization",
            getattr(diarization, "speaker_diarization", diarization),
        )

        turns: List[Tuple[float, float, str]] = []
        for turn, _, speaker in annotation.itertracks(yield_label=True):
            turns.append((float(turn.start), float(turn.end), str(speaker)))

        return turns
    except ImportError:
        raise RuntimeError(
            f"pyannote.audio is not installed.\n{DIARIZATION_SETUP_INSTRUCTIONS}"
        )
    except Exception as e:
        raise RuntimeError(f"Speaker diarization failed: {e}")


def assign_speakers_to_segments(
    segments: List[Dict[str, Any]],
    speaker_turns: List[Tuple[float, float, str]],
) -> List[Dict[str, Any]]:
    """Assign speaker labels to transcript segments based on maximum temporal overlap.

    Also normalizes raw speaker IDs (e.g., 'SPEAKER_00', 'SPEAKER_01') to
    friendly 'Speaker 1', 'Speaker 2', etc. in order of first appearance.
    """
    if not speaker_turns:
        return segments

    # Map raw speaker IDs to "Speaker 1", "Speaker 2", etc.
    speaker_map: Dict[str, str] = {}
    speaker_counter = 1

    for seg in segments:
        seg_start = seg.get("start", 0.0)
        seg_end = seg.get("end", 0.0)
        seg_duration = max(0.001, seg_end - seg_start)

        best_speaker = None
        max_overlap = 0.0

        for turn_start, turn_end, speaker_id in speaker_turns:
            overlap = max(0.0, min(seg_end, turn_end) - max(seg_start, turn_start))
            if overlap > max_overlap:
                max_overlap = overlap
                best_speaker = speaker_id

        # If no direct overlap, pick the turn closest to the segment midpoint
        if not best_speaker:
            midpoint = (seg_start + seg_end) / 2.0
            closest_dist = float("inf")
            for turn_start, turn_end, speaker_id in speaker_turns:
                dist = min(abs(midpoint - turn_start), abs(midpoint - turn_end))
                if dist < closest_dist:
                    closest_dist = dist
                    best_speaker = speaker_id

        if best_speaker:
            if best_speaker not in speaker_map:
                speaker_map[best_speaker] = f"Speaker {speaker_counter}"
                speaker_counter += 1
            seg["speaker"] = speaker_map[best_speaker]
        else:
            seg["speaker"] = "Speaker 1"

    return segments
