import json
import logging
from io import StringIO

from app.logging import StructuredFormatter, logging_context


def test_structured_formatter_includes_review_job_context():
    output = StringIO()
    handler = logging.StreamHandler(output)
    handler.setFormatter(StructuredFormatter())
    logger = logging.getLogger("test.structured")
    previous_level = logger.level
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    logger.propagate = False

    try:
        with logging_context(
            job_id=42,
            repository="owner/repo",
            pull_request_number=17,
            commit_sha="abc123",
        ):
            logger.info("Started review job")
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)
        logger.propagate = True

    record = json.loads(output.getvalue())
    assert record["message"] == "Started review job"
    assert record["job_id"] == 42
    assert record["repository"] == "owner/repo"
    assert record["pull_request_number"] == 17
    assert record["commit_sha"] == "abc123"


def test_structured_formatter_omits_unavailable_job_fields():
    record = logging.LogRecord(
        name="test.structured",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="Application ready",
        args=(),
        exc_info=None,
    )

    payload = json.loads(StructuredFormatter().format(record))

    assert payload["message"] == "Application ready"
    assert "job_id" not in payload
    assert "repository" not in payload
