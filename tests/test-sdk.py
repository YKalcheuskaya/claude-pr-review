"""Exercise the installed official SDK against an in-memory HTTP transport."""
import importlib.util
import json
from pathlib import Path
import unittest

from pr_review.core import ReviewError
from pr_review.service import analyze

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(importlib.util.find_spec("anthropic"), "Install requirements-lock.txt for SDK tests")
class SdkCompatibility(unittest.TestCase):
    def test_real_sdk_serializes_schema_and_parses_response(self):
        import anthropic
        import httpx2
        data = json.loads((ROOT / "evaluation/input.json").read_text())
        content = json.loads((ROOT / "evaluation/defect-response.json").read_text())
        calls = []
        def respond(request):
            calls.append(json.loads(request.content))
            return httpx2.Response(200, json={"id": "msg_fixture", "type": "message",
                "role": "assistant", "model": data["model"], "stop_reason": "end_turn",
                "stop_sequence": None, "content": [{"type": "text", "text": json.dumps(content)}],
                "usage": {"input_tokens": 100, "output_tokens": 60}})
        with httpx2.Client(transport=httpx2.MockTransport(respond)) as http:
            client = anthropic.Anthropic(api_key="fixture-not-a-real-key", http_client=http,
                                         timeout=60, max_retries=0)
            result = analyze(data, client=client)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["output_config"]["format"]["type"], "json_schema")
        self.assertEqual(result["usage"]["output_tokens"], 60)

    def test_sdk_timeout_has_no_retry(self):
        import anthropic
        import httpx2
        data = json.loads((ROOT / "evaluation/input.json").read_text())
        calls = []
        def respond(request):
            calls.append(request)
            raise httpx2.ReadTimeout("fixture timeout")
        with httpx2.Client(transport=httpx2.MockTransport(respond)) as http:
            client = anthropic.Anthropic(api_key="fixture-not-a-real-key", http_client=http,
                                         timeout=60, max_retries=0)
            with self.assertRaises(ReviewError):
                analyze(data, client=client)
        self.assertEqual(len(calls), 1)
