"""Review the latest stored PR with the real model, without posting GitHub comments.

Run inside the configured backend: python -m scripts.tracegrade_smoke [--job-id ID]
"""
import argparse
import os
from pathlib import Path

from sqlalchemy.engine import make_url

from dotenv import load_dotenv

load_dotenv()
# docker exec does not inherit the worker startup shell's database override.
if Path("/.dockerenv").exists():
    url = make_url(os.environ["DATABASE_URL"])
    if url.host in {"localhost", "127.0.0.1"}:
        os.environ["DATABASE_URL"] = url.set(host="postgres").render_as_string(hide_password=False)

from app.ai.review_service import review_code
from app.db.database import SessionLocal
from app.db.models import ReviewJob
from app.services.review_processing_service import _build_diff, _get_files_for_review
from app.tracing import trace_review


@trace_review
def smoke_review(db, job):
    files = _get_files_for_review(job, os.environ['GITHUB_ACCESS_TOKEN'])
    diff = _build_diff(files)
    if not diff.strip():
        raise RuntimeError('Selected review job has no reviewable diff')
    result = review_code(diff)
    print(f'Real model review completed: {len(result.issues)} issues')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job-id', type=int)
    args = parser.parse_args()
    if not os.getenv('TRACEGRADE_API_KEY'):
        parser.error('TRACEGRADE_API_KEY must be configured')
    with SessionLocal() as db:
        query = db.query(ReviewJob)
        if args.job_id:
            query = query.filter(ReviewJob.id == args.job_id)
        job = query.order_by(ReviewJob.id.desc()).first()
        if job is None:
            parser.error('No stored review job found; trigger a PR review first')
        print(f'Reviewing {job.repository} PR #{job.pull_request_number} (job {job.id})')
        smoke_review(db, job)


if __name__ == '__main__':
    import logging
    logging.basicConfig(level=logging.INFO)
    main()
