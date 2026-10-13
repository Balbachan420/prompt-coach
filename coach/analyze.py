"""Background job: decide whether a candidate correction is real and leave a lesson.

Started detached by the UserPromptSubmit hook as `python -m coach.analyze <job>`.
The job file holds the correction text and the transcript path; it is deleted
when the job finishes, whatever the outcome.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from coach import store
from coach.correction import analyze, lesson_text
from coach.session import read_turns


def run_job(job_path: Path) -> dict | None:
    try:
        job = json.loads(job_path.read_text(encoding="utf-8"))
    finally:
        job_path.unlink(missing_ok=True)
    verdict = analyze(read_turns(job["transcript_path"]), job["prompt"])
    if verdict is None:
        return None
    store.append_lesson({"session": job["session"], **verdict})
    if not verdict["is_correction"] or verdict.get("agent_fault"):
        return verdict
    same = sum(
        1
        for lesson in store.read_lessons(days=30)
        if lesson.get("type") == verdict["type"]
        and lesson.get("is_correction")
        and not lesson.get("agent_fault")
    )
    pending = store.pending_path(job["session"])
    pending.parent.mkdir(parents=True, exist_ok=True)
    pending.write_text(json.dumps({"message": lesson_text(verdict, same)}, ensure_ascii=False), encoding="utf-8")
    return verdict


if __name__ == "__main__":
    try:
        run_job(Path(sys.argv[1]))
    except Exception:  # noqa: BLE001 — a background coach bug stays invisible
        pass
