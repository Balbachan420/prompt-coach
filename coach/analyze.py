"""Background job: decide whether a candidate correction is real and leave a lesson.

Started detached by the UserPromptSubmit hook as `python -m coach.analyze <job>`.
The job file holds the correction text and the transcript path; it is deleted
when the job finishes, whatever the outcome.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from coach import retire, store
from coach.correction import LLMError, analyze, lesson_text
from coach.session import read_turns
from coach.sources import read_codex_turns


def run_job(job_path: Path) -> dict | None:
    try:
        job = json.loads(job_path.read_text(encoding="utf-8"))
    finally:
        job_path.unlink(missing_ok=True)
    reader = read_codex_turns if job.get("provider") == "codex" else read_turns
    try:
        verdict = analyze(reader(job["transcript_path"]), job["prompt"])
    except LLMError as error:
        store.log_error("live", str(error))
        return None
    store.append_lesson(
        {"session": job["session"], "provider": job.get("provider", "claude"), "hash": job.get("hash"), **verdict}
    )
    retire.refresh()
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
