import unittest
from unittest.mock import Mock, patch

from app.ai import provider


class AIProviderTests(unittest.TestCase):
    def test_uses_configured_provider_and_model(self):
        factory = Mock(return_value=object())

        with (
            patch.dict(provider._PROVIDER_FACTORIES, {"gemini": factory}, clear=True),
            patch.dict(
                "os.environ",
                {"AI_PROVIDER": "GeMiNi", "AI_MODEL": "gemini-custom"},
                clear=False,
            ),
        ):
            model = provider.create_ai_model()

        self.assertIs(model, factory.return_value)
        factory.assert_called_once_with("gemini-custom")

    def test_defaults_to_gemini(self):
        factory = Mock(return_value=object())

        with (
            patch.dict(provider._PROVIDER_FACTORIES, {"gemini": factory}, clear=True),
            patch.dict("os.environ", {}, clear=False),
            patch.object(provider.os, "getenv") as getenv,
        ):
            getenv.side_effect = lambda key, default=None: default
            provider.create_ai_model()

        factory.assert_called_once_with(provider.DEFAULT_AI_MODEL)

    def test_rejects_unsupported_provider_with_actionable_message(self):
        with (
            patch.dict(provider._PROVIDER_FACTORIES, {"gemini": Mock()}, clear=True),
            patch.dict(
                "os.environ",
                {"AI_PROVIDER": "groq", "AI_MODEL": "llama"},
                clear=False,
            ),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "Unsupported AI_PROVIDER 'groq'.*gemini",
            ):
                provider.create_ai_model()

    def test_creates_structured_output_at_provider_boundary(self):
        base_model = Mock()
        schema = type("Schema", (), {})

        with patch.object(provider, "create_ai_model", return_value=base_model):
            result = provider.create_structured_model(schema)

        self.assertIs(result, base_model.with_structured_output.return_value)
        base_model.with_structured_output.assert_called_once_with(
            schema,
            method="json_schema",
        )


if __name__ == "__main__":
    unittest.main()
