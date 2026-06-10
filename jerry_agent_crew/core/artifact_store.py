from __future__ import annotations

import re
from pathlib import Path
from typing import List

from .models import Artifact, CrewTask


ARTIFACT_ROOT = Path(__file__).resolve().parents[1] / "artifacts"


def _safe_name(value: str) -> str:
    value = re.sub(r"[^\w\u4e00-\u9fff.-]+", "_", value.strip(), flags=re.UNICODE)
    return value[:60].strip("_") or "artifact"


def write_artifacts(task: CrewTask) -> List[str]:
    run_dir = ARTIFACT_ROOT / task.run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    paths: List[str] = []
    for index, artifact in enumerate(task.artifacts, start=1):
        suffix = "md"
        if artifact.kind in {"csv", "json", "txt"}:
            suffix = artifact.kind
        filename = f"{index:02d}_{_safe_name(artifact.title)}.{suffix}"
        path = run_dir / filename
        path.write_text(artifact.content, encoding="utf-8")
        artifact.metadata["path"] = str(path)
        paths.append(str(path))
    return paths

