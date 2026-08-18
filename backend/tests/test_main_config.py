from unittest.mock import patch

from app.main import _cors_allowed_origins


def test_cors_allowed_origins_have_local_defaults():
    with patch.dict("os.environ", {}, clear=True):
        assert _cors_allowed_origins() == [
            "http://localhost:5173",
            "http://localhost:3000",
        ]


def test_cors_allowed_origins_are_parsed_and_normalized():
    with patch.dict(
        "os.environ",
        {
            "CORS_ALLOWED_ORIGINS": (
                "https://review.example.com/, https://admin.example.com , "
            )
        },
        clear=True,
    ):
        assert _cors_allowed_origins() == [
            "https://review.example.com",
            "https://admin.example.com",
        ]

