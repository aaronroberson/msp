import json
import os
import unittest
from typing import Any
from unittest import mock
from urllib.request import Request

from src import llm


class FakeProvider:
    name = "fake"

    def complete_json(self, prompt, payload):
        self.prompt = prompt
        self.payload = payload
        return {
            "summary": "fake summary",
            "risk_assessment": "medium",
            "recommended_next_steps": "review findings",
            "confidence": "0.9",
        }


class LLMTest(unittest.TestCase):
    def test_local_provider_returns_structured_reasoning(self):
        provider = llm.LocalHeuristicProvider()
        result = provider.complete_json(
            "prompt",
            {
                "facts": {"network": {}, "tcc": {}},
                "findings": [
                    {"severity": "high", "category": "firewall", "title": "Firewall disabled"},
                    {"severity": "medium", "category": "tcc", "title": "Broad TCC grant"},
                ],
            },
        )

        self.assertIn("Reviewed 2 fact sections", result["summary"])
        self.assertEqual(result["risk_assessment"]["level"], "high")
        self.assertEqual(result["risk_assessment"]["by_category"]["firewall"], 1)
        self.assertGreaterEqual(len(result["recommended_next_steps"]), 2)

    def test_reasoner_coerces_provider_output(self):
        provider = FakeProvider()
        reasoner = llm.LLMReasoner(provider=provider)
        result = reasoner.analyze({"section": {}}, [{"severity": "low"}], {"actions": []})

        self.assertEqual(result["summary"], "fake summary")
        self.assertEqual(result["risk_assessment"], {"level": "medium"})
        self.assertEqual(result["recommended_next_steps"], ["review findings"])
        self.assertEqual(result["confidence"], 0.9)
        self.assertEqual(result["provider"], "fake")
        self.assertIn("facts", provider.payload)

    def test_choose_provider_defaults_to_local_when_no_external_provider_available(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with (mock.patch("src.llm.OllamaProvider.available", return_value=False)):
                with mock.patch("src.llm.ApfelProvider.available", return_value=False):
                    provider = llm.choose_provider()

        self.assertIsInstance(provider, llm.LocalHeuristicProvider)

    def test_choose_provider_ollama_when_available(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with (mock.patch("src.llm.OllamaProvider.available", return_value=True)):
                provider = llm.choose_provider()

        self.assertIsInstance(provider, llm.OllamaProvider)
        self.assertEqual(provider.name, "ollama")

    def test_choose_provider_ollama_explicit(self):
        provider = llm.choose_provider("ollama")
        self.assertIsInstance(provider, llm.OllamaProvider)
        self.assertEqual(provider.name, "ollama")

    def _make_cm(self, data: bytes, status: int = 200) -> mock.MagicMock:
        """Build a proper context manager mock for urlopen."""
        cm = mock.MagicMock()
        cm.__enter__.return_value = cm
        cm.__exit__.return_value = None
        cm.status = status
        cm.read.return_value = data
        return cm

    def test_ollama_provider_invokes_api_and_parses_json(self):
        fake_content = json.dumps({
            "summary": "ollama summary",
            "risk_assessment": {"level": "low"},
            "recommended_next_steps": [],
            "confidence": 0.85,
        })
        chat_response = json.dumps({
            "message": {"content": fake_content, "role": "assistant"},
            "done": True,
        }).encode("utf-8")
        tags_response = json.dumps({"models": [{"name": "qwen2.5-coder:1.5b"}]}).encode("utf-8")

        def side_effect(req: Request, **kwargs: Any) -> mock.MagicMock:
            if "/api/tags" in req.full_url:
                return self._make_cm(tags_response)
            return self._make_cm(chat_response)

        with mock.patch("src.llm.urlopen", side_effect=side_effect):
            provider = llm.OllamaProvider(model="qwen2.5-coder:1.5b")
            result = provider.complete_json("analyze", {"facts": {}})

        self.assertEqual(result["summary"], "ollama summary")
        self.assertEqual(result["risk_assessment"]["level"], "low")
        self.assertEqual(result["confidence"], 0.85)

    def test_ollama_provider_sends_json_mode(self):
        fake_content = json.dumps({
            "summary": "test",
            "risk_assessment": {"level": "low"},
            "recommended_next_steps": [],
            "confidence": 0.5,
        })
        chat_response = json.dumps({
            "message": {"content": fake_content, "role": "assistant"},
            "done": True,
        }).encode("utf-8")
        tags_response = json.dumps({"models": [{"name": "qwen2.5-coder:1.5b"}]}).encode("utf-8")

        captured = []

        def side_effect(req: Request, **kwargs: Any) -> mock.MagicMock:
            if "/api/tags" in req.full_url:
                return self._make_cm(tags_response)
            captured.append(req)
            return self._make_cm(chat_response)

        with mock.patch("src.llm.urlopen", side_effect=side_effect):
            provider = llm.OllamaProvider(model="qwen2.5-coder:1.5b")
            provider.complete_json("analyze", {"facts": {}})

        req = captured[0]
        self.assertIn("/api/chat", req.full_url)
        self.assertEqual(req.method, "POST")
        body = json.loads(req.data)
        self.assertEqual(body["format"], "json")
        self.assertEqual(body["model"], "qwen2.5-coder:1.5b")
        self.assertEqual(body["options"]["num_ctx"], 2048)
        self.assertIn("analyze", body["messages"][1]["content"])

    def test_ollama_provider_available_returns_true_when_running(self):
        cm = mock.MagicMock()
        cm.status = 200

        with mock.patch("src.llm.urlopen", return_value=cm) as urlopen_mock:
            cm.__enter__.return_value = cm
            result = llm.OllamaProvider.available()

        self.assertTrue(result)
        called_req = urlopen_mock.call_args.args[0]
        self.assertIn("/api/tags", called_req.full_url)

    def test_ollama_provider_available_returns_false_when_not_running(self):
        from urllib.error import URLError

        with mock.patch("src.llm.urlopen", side_effect=URLError("Connection refused")):
            result = llm.OllamaProvider.available()

        self.assertFalse(result)

    def test_ollama_provider_raises_on_empty_response(self):
        chat_response = json.dumps({
            "message": {"content": "", "role": "assistant"},
            "done": True,
        }).encode("utf-8")
        tags_response = json.dumps({"models": [{"name": "qwen2.5-coder:1.5b"}]}).encode("utf-8")

        def side_effect(req: Request, **kwargs: Any) -> mock.MagicMock:
            if "/api/tags" in req.full_url:
                return self._make_cm(tags_response)
            return self._make_cm(chat_response)

        with mock.patch("src.llm.urlopen", side_effect=side_effect):
            provider = llm.OllamaProvider(model="qwen2.5-coder:1.5b")
            with self.assertRaises(RuntimeError) as ctx:
                provider.complete_json("analyze", {"facts": {}})
            self.assertIn("empty", str(ctx.exception).lower())

    def test_ollama_provider_raises_on_non_json_content(self):
        chat_response = json.dumps({
            "message": {"content": "I think the answer is...", "role": "assistant"},
            "done": True,
        }).encode("utf-8")
        tags_response = json.dumps({"models": [{"name": "qwen2.5-coder:1.5b"}]}).encode("utf-8")

        def side_effect(req: Request, **kwargs: Any) -> mock.MagicMock:
            if "/api/tags" in req.full_url:
                return self._make_cm(tags_response)
            return self._make_cm(chat_response)

        with mock.patch("src.llm.urlopen", side_effect=side_effect):
            provider = llm.OllamaProvider(model="qwen2.5-coder:1.5b")
            with self.assertRaises(RuntimeError) as ctx:
                provider.complete_json("analyze", {"facts": {}})
            self.assertIn("non-JSON", str(ctx.exception))

    def test_ollama_provider_raises_on_non_object_response(self):
        chat_response = json.dumps({
            "message": {"content": '"just a string"', "role": "assistant"},
            "done": True,
        }).encode("utf-8")
        tags_response = json.dumps({"models": [{"name": "qwen2.5-coder:1.5b"}]}).encode("utf-8")

        def side_effect(req: Request, **kwargs: Any) -> mock.MagicMock:
            if "/api/tags" in req.full_url:
                return self._make_cm(tags_response)
            return self._make_cm(chat_response)

        with mock.patch("src.llm.urlopen", side_effect=side_effect):
            provider = llm.OllamaProvider(model="qwen2.5-coder:1.5b")
            with self.assertRaises(RuntimeError) as ctx:
                provider.complete_json("analyze", {"facts": {}})
            self.assertIn("non-object", str(ctx.exception))

    def test_openai_provider_is_lazy_and_requires_api_key(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            provider = llm.OpenAIProvider()
            with self.assertRaises(RuntimeError):
                provider.complete_json("prompt", {})

    def test_apfel_provider_invokes_executable_and_parses_json(self):
        completed = mock.Mock()
        completed.returncode = 0
        completed.stdout = json.dumps(
            {
                "summary": "apfel summary",
                "risk_assessment": {"level": "low"},
                "recommended_next_steps": [],
                "confidence": 0.5,
            }
        )
        completed.stderr = ""

        with mock.patch("src.llm.shutil.which", return_value="/bin/apfel"):
            with mock.patch("src.llm.subprocess.run", return_value=completed) as run:
                provider = llm.ApfelProvider(executable="apfel")
                result = provider.complete_json("prompt", {"facts": {}})

        self.assertEqual(result["summary"], "apfel summary")
        self.assertEqual(run.call_args.args[0], ["apfel", "reason", "--json"])

    def test_unknown_provider_name_raises(self):
        with self.assertRaises(ValueError):
            llm.choose_provider("not-a-provider")


class AIHelpersTest(unittest.TestCase):
    def test_extract_commands_from_text(self):
        from src.ai import _extract_commands

        text = """PID 563 is using 2.3GB RAM.
  $ ps -p 563 -o pid,rss,command
  $ kill -9 563
Some more explanation.
  sudo lsof -i :80"""

        cmds = _extract_commands(text)
        self.assertIn("ps -p 563 -o pid,rss,command", cmds)
        self.assertIn("kill -9 563", cmds)
        self.assertIn("sudo lsof -i :80", cmds)

    def test_extract_commands_deduplicates(self):
        from src.ai import _extract_commands

        text = """Run this:
  $ kill -9 563
Or this:
  $ kill -9 563"""

        cmds = _extract_commands(text)
        self.assertEqual(len(cmds), 1)
        self.assertEqual(cmds[0], "kill -9 563")

    def test_extract_commands_skips_junk(self):
        from src.ai import _extract_commands

        text = """Here's my analysis:
The system looks fine overall.
No action needed."""
        cmds = _extract_commands(text)
        self.assertEqual(len(cmds), 0)

    def test_extract_commands_inside_code_block(self):
        from src.ai import _extract_commands

        text = """Check running processes:
```
ps aux --sort=-%mem | head -10
```"""
        cmds = _extract_commands(text)
        self.assertIn("ps aux --sort=-%mem | head -10", cmds)



if __name__ == "__main__":
    unittest.main()
