import json
import os
import unittest
from unittest import mock

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
            with mock.patch("src.llm.ApfelProvider.available", return_value=False):
                provider = llm.choose_provider()

        self.assertIsInstance(provider, llm.LocalHeuristicProvider)

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


if __name__ == "__main__":
    unittest.main()
