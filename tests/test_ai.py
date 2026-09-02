import json
import os
import unittest
from unittest import mock
from urllib.error import HTTPError
from urllib.request import Request

from src import ai


class AIBYOKTest(unittest.TestCase):
    def test_config_load_and_save(self):
        with mock.patch("src.ai.AI_CONFIG_FILE", ai.CONFIG_DIR / "test_ai_config.json"):
            cfg = {"default_provider": "groq", "providers": {"groq": {"model": "llama-3.3-70b-versatile"}}}
            ai.save_ai_config(cfg)
            loaded = ai.load_ai_config()
            self.assertEqual(loaded["default_provider"], "groq")
            if (ai.CONFIG_DIR / "test_ai_config.json").exists():
                (ai.CONFIG_DIR / "test_ai_config.json").unlink()

    def test_key_resolution_order(self):
        # 1. Environment variable wins
        with mock.patch.dict(os.environ, {"GROQ_API_KEY": "env-key-123"}):
            with mock.patch("src.ai.get_keychain_key", return_value="keychain-key-456"):
                self.assertEqual(ai.get_resolved_api_key("groq"), "env-key-123")

        # 2. Keychain key used when env var is unset
        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch("src.ai.get_keychain_key", return_value="keychain-key-456"):
                self.assertEqual(ai.get_resolved_api_key("groq"), "keychain-key-456")

    def test_http_chat_completion_success(self):
        fake_resp = json.dumps({
            "choices": [{"message": {"content": "Hello from Groq"}}]
        }).encode("utf-8")

        cm = mock.MagicMock()
        cm.read.return_value = fake_resp
        cm.__enter__.return_value = cm

        with mock.patch("src.ai.urlopen", return_value=cm):
            out = ai._http_chat_completion(
                provider_name="groq",
                base_url="https://api.groq.com/openai/v1",
                api_key="gsk_test",
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": "hi"}],
            )
            self.assertEqual(out, "Hello from Groq")

    def test_http_chat_completion_parses_http_error_json(self):
        error_body = json.dumps({"error": {"message": "You exceeded your current quota"}}).encode("utf-8")
        fp = mock.MagicMock()
        fp.read.return_value = error_body
        http_err = HTTPError(url="https://api.openai.com/v1", code=429, msg="Too Many Requests", hdrs={}, fp=fp)

        with mock.patch("src.ai.urlopen", side_effect=http_err):
            with self.assertRaises(RuntimeError) as ctx:
                ai._http_chat_completion(
                    provider_name="openai",
                    base_url="https://api.openai.com/v1",
                    api_key="sk-test",
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": "hi"}],
                )
            self.assertIn("429", str(ctx.exception))
            self.assertIn("You exceeded your current quota", str(ctx.exception))

    def test_analyzer_transparent_fallback(self):
        analyzer = ai.AIAnalyzer(provider="openai")

        # Mock primary provider failure (e.g. 429 quota error)
        # Mock apfel fallback success
        with mock.patch.object(analyzer, "_resolve_active_provider", return_value=("openai", "https://api.openai.com/v1", "gpt-4o-mini", "sk-test")):
            with mock.patch("src.ai._http_chat_completion", side_effect=RuntimeError("[openai HTTP 429] Out of credits")):
                with mock.patch("src.ai._apfel_available", return_value=True):
                    with mock.patch("src.ai._apfel_chat", return_value="Fallback response from apfel"):
                        res = analyzer._chat("system prompt", "user question")
                        self.assertEqual(res, "Fallback response from apfel")


if __name__ == "__main__":
    unittest.main()
