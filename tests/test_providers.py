import json
import io
import socket
import urllib.error
import unittest
from unittest.mock import patch
from pathlib import Path

from rundale_bench.providers import NativeClient, ProviderError, _UrllibTransport, load_profiles, resolve_profile


class FakeTransport:
    def __init__(self, data, status=200): self.data, self.status, self.calls = data, status, []
    def post(self, url, headers, body, timeout=180):
        self.calls.append((url, headers, json.loads(body), timeout))
        return self.status, json.dumps(self.data).encode()


class FakeStream:
    def __init__(self, lines, error=None, status=200): self.lines, self.error, self.status, self.closed = lines, error, status, False
    def __enter__(self): return self
    def __exit__(self, *exc): self.closed = True
    def __iter__(self):
        for line in self.lines: yield line
        if self.error: raise self.error


class FakeStreamingTransport:
    def __init__(self, lines, error=None, status=200): self.stream = FakeStream(lines, error, status); self.calls = []
    def stream_post(self, url, headers, body, timeout=180):
        self.calls.append((url, headers, json.loads(body), timeout))
        return self.stream


class ProviderTests(unittest.TestCase):
    def profile(self, provider="openai", **extra):
        return {"id":"test", "provider":provider, "model":"test-model", "reasoning":"high", "api_key_env":"TEST_KEY", **extra}

    def test_profiles_exact_reasoning_snapshots_and_pricing(self):
        registry = load_profiles(Path(__file__).parents[1] / "config/providers.json")
        self.assertEqual(resolve_profile("gpt-6.1-sol", registry=registry)["reasoning"], "max")
        self.assertEqual(resolve_profile("gpt-6.1-sol", "high", registry)["id"], "gpt-6.1-sol-judge-high")
        with self.assertRaises(ValueError): resolve_profile("gemini-3.5-flash-lite", "max", registry)
        self.assertIsNone(registry["claude-sonnet-4-6"]["input_per_million_usd"])
        self.assertEqual(registry["gpt-6.1-sol-judge-high"]["supported_reasoning"], ["low", "medium", "high", "xhigh", "max"])
        self.assertEqual(registry["jev-1.13.0"]["input_per_million_usd"], 0.042)
        self.assertEqual(registry["gemini-3.5-flash-lite"]["supported_reasoning"], ["minimal", "low", "medium", "high"])
        with self.assertRaisesRegex(ValueError, "disabled"): resolve_profile("gemini-3.7-flash", registry=registry)
        opus = registry["claude-opus-5-5-judge-high"]
        self.assertEqual((opus["model"], opus["reasoning"], opus["input_per_million_usd"], opus["output_per_million_usd"], opus["cached_input_per_million_usd"]), ("claude-opus-5-5", "high", 4.0, 20.0, .20))
        self.assertEqual(opus["supported_reasoning"], ["low", "medium", "high", "xhigh", "max"])
        self.assertEqual(opus["judge_max_output_tokens"], 16384)
        with self.assertRaisesRegex(ValueError, "disabled"): resolve_profile("claude-opus-5-5", registry=registry)

    def test_anthropic_effort_and_judge_schema_request(self):
        fake = FakeTransport({"id":"msg_1","type":"message","model":"claude-opus-5-5","content":[{"type":"text","text":"{}"}],"stop_reason":"end_turn","usage":{"input_tokens":10,"output_tokens":2,"cache_read_input_tokens":3}})
        profile = {"id":"opus","provider":"anthropic","model":"claude-opus-5-5","reasoning":"high","api_key_env":"TEST_KEY"}
        NativeClient({"TEST_KEY":"secret"}, fake).generate(profile, [{"role":"system","content":"judge"},{"role":"user","content":"{}"}], 50, response_schema={"type":"object"})
        body = fake.calls[0][2]
        self.assertEqual(body["output_config"]["effort"], "high")
        self.assertEqual(body["output_config"]["format"], {"type":"json_schema","schema":{"type":"object"}})

    def test_openai_native_response_usage_and_request(self):
        fake = FakeTransport({"model":"gpt-6.1-sol", "output_text":"hello", "usage":{"input_tokens":10,"input_tokens_details":{"cached_tokens":4},"output_tokens":7,"output_tokens_details":{"reasoning_tokens":3}}})
        result = NativeClient({"TEST_KEY":"secret"}, fake).generate(self.profile(), [{"role":"user","content":"hi"}], 50)
        self.assertEqual(result.text, "hello")
        self.assertEqual(result.usage, {"input_tokens":10,"cached_input_tokens":4,"output_tokens":7,"reasoning_tokens":3})
        url, headers, body, _ = fake.calls[0]
        self.assertEqual(url, "https://api.openai.com/v1/responses")
        self.assertEqual(body["reasoning"], {"effort":"high"})
        self.assertEqual(headers["Authorization"], "Bearer secret")

    def test_google_gemini_usage_and_cache_pricing_fields(self):
        fake = FakeTransport({"model":"gemini-3.7-flash","candidates":[{"content":{"parts":[{"text":"ok"}]}}],"usageMetadata":{"promptTokenCount":100,"cachedContentTokenCount":40,"candidatesTokenCount":20,"thoughtsTokenCount":5}})
        profile = self.profile("google", model="gemini-3.7-flash", reasoning="high")
        result = NativeClient({"TEST_KEY":"s"}, fake).generate(profile, [{"role":"user","content":"x"}], 30)
        self.assertEqual(result.usage["cached_input_tokens"], 40)
        self.assertEqual(result.usage["output_tokens"], 25)
        self.assertEqual(result.raw["usageMetadata"]["thoughtsTokenCount"], 5)
        self.assertEqual(result.usage["reasoning_tokens"], 5)
        self.assertIsNone(result.ttft_ms)  # This fake deliberately exercises nonstream fallback.
        self.assertEqual(fake.calls[0][2]["generationConfig"]["thinkingConfig"], {"thinkingLevel":"high"})

    def test_google_sse_measures_first_non_thought_nonempty_text(self):
        lines = [
            b'data: {"candidates":[{"content":{"parts":[{"text":"private thought","thought":true}]}}]}\n',
            b'data: {"candidates":[{"content":{"parts":[{"text":""}]}}]}\n',
            b'data: {"candidates":[{"content":{"parts":[{"text":"Hello"}]}}]}\n',
            b'data: {"modelVersion":"gemini-3.7-flash","candidates":[{"finishReason":"STOP","content":{"parts":[{"text":" world"}]}}],"usageMetadata":{"promptTokenCount":100,"cachedContentTokenCount":40,"candidatesTokenCount":20,"thoughtsTokenCount":5}}\n',
        ]
        transport = FakeStreamingTransport(lines)
        profile = self.profile("google", model="gemini-3.7-flash", reasoning="high")
        with patch("rundale_bench.providers.time.monotonic", side_effect=[10.0, 11.5, 14.0]):
            result = NativeClient({"TEST_KEY":"key"}, transport).generate(profile, [{"role":"user","content":"x"}], 30)
        self.assertEqual(result.text, "Hello world")
        self.assertEqual(result.ttft_ms, 1500.0)
        self.assertEqual(result.elapsed_ms, 4000.0)
        self.assertEqual(result.usage["output_tokens"], 25)
        self.assertEqual(len(result.raw["stream_chunks"]), 4)
        self.assertEqual(result.model, "gemini-3.7-flash")
        url, headers, body, timeout = transport.calls[0]
        self.assertTrue(url.endswith(":streamGenerateContent?alt=sse"))
        self.assertEqual(headers["x-goog-api-key"], "key")
        self.assertEqual(timeout, 180)
        self.assertEqual(body["generationConfig"]["thinkingConfig"], {"thinkingLevel":"high"})
        self.assertTrue(transport.stream.closed)

    def test_google_stream_failure_with_usage_preserves_metering_without_retry(self):
        lines = [b'data: {"candidates":[{"content":{"parts":[{"text":"partial"}]}}],"usageMetadata":{"promptTokenCount":20,"candidatesTokenCount":3,"thoughtsTokenCount":1}}\n']
        transport = FakeStreamingTransport(lines, OSError("stream stopped"))
        profile = self.profile("google", model="gemini-3.7-flash", reasoning="high")
        with self.assertRaises(ProviderError) as caught:
            NativeClient({"TEST_KEY":"key"}, transport).generate(profile, [{"role":"user","content":"x"}], 30)
        self.assertEqual(caught.exception.kind, "transport")
        self.assertTrue(caught.exception.billing_uncertain)
        self.assertEqual(caught.exception.payload["partial_text"], "partial")
        self.assertEqual(len(caught.exception.payload["chunks"]), 1)
        self.assertEqual(caught.exception.payload["usage"], {"input_tokens":20,"cached_input_tokens":0,"output_tokens":4,"reasoning_tokens":1})
        self.assertEqual(len(transport.calls), 1)

    def test_google_stream_malformed_chunk_after_usage_stays_uncertain(self):
        lines = [
            b'data: {"candidates":[{"content":{"parts":[{"text":"partial"}]}}],"usageMetadata":{"promptTokenCount":20,"candidatesTokenCount":3,"thoughtsTokenCount":1}}\n',
            b'data: {"candidates":\n',
        ]
        transport = FakeStreamingTransport(lines)
        profile = self.profile("google", model="gemini-3.7-flash", reasoning="high")
        with self.assertRaises(ProviderError) as caught:
            NativeClient({"TEST_KEY":"key"}, transport).generate(profile, [], 30)
        self.assertEqual(caught.exception.kind, "malformed")
        self.assertTrue(caught.exception.billing_uncertain)
        self.assertEqual(caught.exception.payload["usage"], {"input_tokens":20,"cached_input_tokens":0,"output_tokens":4,"reasoning_tokens":1})

    def test_non_object_native_http_errors_remain_provider_errors(self):
        profile = self.profile()
        for status, body, kind in ((401, ["bad body"], "auth"), (429, None, "provider")):
            with self.subTest(status=status):
                with self.assertRaises(ProviderError) as caught:
                    NativeClient({"TEST_KEY":"key"}, FakeTransport(body, status)).generate(profile, [], 10)
                self.assertEqual(caught.exception.kind, kind)
                self.assertFalse(caught.exception.billing_uncertain)
                self.assertNotIn("usage", caught.exception.payload)

    def test_non_object_success_body_is_malformed_and_billing_uncertain(self):
        for body in ([], "bad body", None):
            with self.subTest(body=body):
                with self.assertRaises(ProviderError) as caught:
                    NativeClient({"TEST_KEY":"key"}, FakeTransport(body)).generate(self.profile(), [], 10)
                self.assertEqual(caught.exception.kind, "malformed")
                self.assertTrue(caught.exception.billing_uncertain)

    def test_google_stream_non_object_http_errors_remain_provider_errors(self):
        profile = self.profile("google", model="gemini-3.7-flash")
        for status, body, kind in ((401, ["bad body"], "auth"), (429, None, "provider")):
            with self.subTest(status=status):
                with self.assertRaises(ProviderError) as caught:
                    NativeClient({"TEST_KEY":"key"}, FakeStreamingTransport([json.dumps(body).encode()], status=status)).generate(profile, [], 10)
                self.assertEqual(caught.exception.kind, kind)
                self.assertFalse(caught.exception.billing_uncertain)
                self.assertNotIn("usage", caught.exception.payload)

    def test_google_stream_non_object_event_is_malformed_and_uncertain(self):
        transport = FakeStreamingTransport([b'data: []\n'])
        with self.assertRaises(ProviderError) as caught:
            NativeClient({"TEST_KEY":"key"}, transport).generate(self.profile("google", model="gemini-3.7-flash"), [], 10)
        self.assertEqual(caught.exception.kind, "malformed")
        self.assertTrue(caught.exception.billing_uncertain)

    def test_google_stream_without_terminal_finish_reason_is_not_success(self):
        lines = [b'data: {"candidates":[{"content":{"parts":[{"text":"partial"}]}}],"usageMetadata":{"promptTokenCount":20,"candidatesTokenCount":3,"thoughtsTokenCount":1}}\n']
        with self.assertRaises(ProviderError) as caught:
            NativeClient({"TEST_KEY":"key"}, FakeStreamingTransport(lines)).generate(self.profile("google", model="gemini-3.7-flash"), [], 10)
        self.assertEqual(caught.exception.kind, "malformed")
        self.assertTrue(caught.exception.billing_uncertain)
        self.assertEqual(caught.exception.payload["partial_text"], "partial")

    def test_stream_transport_error_has_safe_dns_diagnostics(self):
        class FailedOpener:
            def open(self, request, timeout=None):
                raise urllib.error.URLError(socket.gaierror(8, "private endpoint secret"))
        with patch("urllib.request.build_opener", return_value=FailedOpener()):
            with self.assertRaises(ProviderError) as caught:
                _UrllibTransport().stream_post("https://api.example.test/private", {}, b"{}")
        self.assertTrue(caught.exception.billing_uncertain)
        self.assertEqual(caught.exception.payload["transport"], {"exception_type":"URLError","reason_type":"gaierror","errno":8})
        self.assertNotIn("private endpoint secret", json.dumps(caught.exception.payload))
        self.assertNotIn("api.example.test", json.dumps(caught.exception.payload))

    def test_google_missing_thought_usage_is_uncertain_not_zero_cost(self):
        fake = FakeTransport({"model":"gemini-3.7-flash","candidates":[{"content":{"parts":[{"text":"ok"}]}}],"usageMetadata":{"promptTokenCount":100,"candidatesTokenCount":20}})
        profile = self.profile("google", model="gemini-3.7-flash", reasoning="high")
        with self.assertRaises(ProviderError) as caught:
            NativeClient({"TEST_KEY":"s"}, fake).generate(profile, [{"role":"user","content":"x"}], 30)
        self.assertTrue(caught.exception.billing_uncertain)

    def test_google_missing_thoughts_with_corroborated_zero_residual_is_known(self):
        fake = FakeTransport({"model":"gemini-3.7-flash","candidates":[{"content":{"parts":[{"text":"ok"}]}}],
                              "usageMetadata":{"promptTokenCount":2883,"candidatesTokenCount":95,"totalTokenCount":2978}})
        result = NativeClient({"TEST_KEY":"s"}, fake).generate(
            self.profile("google", model="gemini-3.7-flash", reasoning="high"), [{"role":"user","content":"x"}], 100)
        self.assertEqual(result.usage, {"input_tokens":2883,"cached_input_tokens":0,"output_tokens":95,"reasoning_tokens":0})

    def test_google_sse_terminal_usage_with_corroborated_zero_thoughts_is_known(self):
        lines = [b'data: {"candidates":[{"finishReason":"STOP","content":{"parts":[{"text":"ok"}]}}],"usageMetadata":{"promptTokenCount":2883,"candidatesTokenCount":95,"totalTokenCount":2978}}\n']
        result = NativeClient({"TEST_KEY":"s"}, FakeStreamingTransport(lines)).generate(
            self.profile("google", model="gemini-3.7-flash", reasoning="high"), [{"role":"user","content":"x"}], 100)
        self.assertEqual(result.usage["output_tokens"], 95)
        self.assertEqual(result.usage["reasoning_tokens"], 0)

    def test_google_missing_thoughts_requires_exact_zero_residual_without_tools(self):
        base = {"promptTokenCount":10,"candidatesTokenCount":5,"totalTokenCount":15}
        invalid = (
            {"promptTokenCount":10,"candidatesTokenCount":5},
            {**base,"totalTokenCount":16},
            {"promptTokenCount":10,"candidatesTokenCount":5,"totalTokenCount":20},
            {**base,"toolUsePromptTokenCount":2},
            {**base,"toolUsePromptTokenCount":True},
            {"promptTokenCount":10,"candidatesTokenCount":5,"totalTokenCount":15.0},
            {"promptTokenCount":10,"candidatesTokenCount":5,"totalTokenCount":None},
            {"promptTokenCount":10,"candidatesTokenCount":5,"totalTokenCount":True},
            {"promptTokenCount":10,"candidatesTokenCount":5,"totalTokenCount":-1},
            {"promptTokenCount":-1,"candidatesTokenCount":5,"totalTokenCount":4},
        )
        for usage in invalid:
            with self.subTest(usage=usage):
                response = {"candidates":[{"content":{"parts":[{"text":"ok"}]}}],"usageMetadata":usage}
                with self.assertRaises(ProviderError) as caught:
                    NativeClient({"TEST_KEY":"s"}, FakeTransport(response)).generate(
                        self.profile("google", model="gemini-3.7-flash"), [], 30)
                self.assertTrue(caught.exception.billing_uncertain)

    def test_google_explicit_thought_count_remains_canonical(self):
        usage = {"promptTokenCount":10,"candidatesTokenCount":5,"thoughtsTokenCount":2,"totalTokenCount":17}
        canonical = NativeClient._parse("google", {"candidates":[{"content":{"parts":[{"text":"ok"}]}}], "usageMetadata":usage})[1]
        self.assertEqual(canonical["output_tokens"], 7)
        self.assertEqual(canonical["reasoning_tokens"], 2)

    def test_domain_allowlist_rejects_openrouter_before_transport(self):
        fake = FakeTransport({})
        p = self.profile(base_url="https://openrouter.ai/api")
        with self.assertRaises(ProviderError) as caught:
            NativeClient({"TEST_KEY":"secret"}, fake).generate(p, [], 10)
        self.assertEqual(caught.exception.kind, "malformed")
        self.assertFalse(fake.calls)

    def test_api_key_is_not_in_error_payload_or_message(self):
        fake = FakeTransport({"error":{"message":"bad","api_key":"leak"}}, status=401)
        with self.assertRaises(ProviderError) as caught:
            NativeClient({"TEST_KEY":"secret"}, fake).generate(self.profile(), [], 10)
        self.assertNotIn("secret", str(caught.exception))
        self.assertNotIn("leak", json.dumps(caught.exception.payload))

    def test_api_key_echo_is_redacted_from_generated_text(self):
        fake = FakeTransport({"model":"test-model","output_text":"The key is secret","usage":{"input_tokens":1,"output_tokens":2}})
        response = NativeClient({"TEST_KEY":"secret"}, fake).generate(self.profile(), [], 10)
        self.assertEqual(response.text, "The key is [REDACTED]")
        self.assertNotIn("secret", json.dumps(response.raw))

    def test_missing_usage_marks_billing_uncertain(self):
        fake = FakeTransport({"output_text":"answer"})
        with self.assertRaises(ProviderError) as caught:
            NativeClient({"TEST_KEY":"secret"}, fake).generate(self.profile(), [], 10)
        self.assertTrue(caught.exception.billing_uncertain)

    def test_anthropic_messages_native_wire_and_cache_usage(self):
        fake = FakeTransport({"model":"claude-sonnet-4-6","content":[{"type":"text","text":"hello"}],"stop_reason":"end_turn","usage":{"input_tokens":12,"cache_read_input_tokens":8,"cache_creation_input_tokens":3,"output_tokens":5}})
        profile = self.profile("anthropic", model="claude-sonnet-4-6")
        result = NativeClient({"TEST_KEY":"s"}, fake).generate(profile, [{"role":"system","content":"rules"},{"role":"user","content":"hi"}], 44)
        url, headers, body, _ = fake.calls[0]
        self.assertEqual(url, "https://api.anthropic.com/v1/messages")
        self.assertEqual(headers["anthropic-version"], "2023-06-01")
        self.assertEqual(body["system"], "rules")
        self.assertEqual(body["output_config"]["effort"], "high")
        self.assertEqual(result.usage["cached_input_tokens"], 8)
        self.assertEqual(result.usage["cache_write_input_tokens"], 3)
        self.assertEqual(result.usage["input_tokens"], 23)

    def test_opus_adaptive_thinking_is_explicit_in_native_request(self):
        fake = FakeTransport({"model":"claude-opus-5-5","content":[{"type":"text","text":"{}"}],"stop_reason":"end_turn","usage":{"input_tokens":5,"output_tokens":3}})
        profile = {"id":"opus","provider":"anthropic","model":"claude-opus-5-5","reasoning":"high","thinking_enabled":True,"api_key_env":"TEST_KEY"}
        NativeClient({"TEST_KEY":"secret"}, fake).generate(profile, [{"role":"user","content":"judge"}], 44, response_schema={"type":"object"})
        body = fake.calls[0][2]
        self.assertEqual(body["thinking"], {"type":"adaptive"})
        self.assertEqual(body["output_config"], {"effort":"high","format":{"type":"json_schema","schema":{"type":"object"}}})

    def test_actual_provider_refusal_not_plain_text_npc_refusal(self):
        fake = FakeTransport({"error":{"code":"content_filter","message":"blocked"}}, status=400)
        with self.assertRaises(ProviderError) as caught:
            NativeClient({"TEST_KEY":"secret"}, fake).generate(self.profile(), [], 10)
        self.assertEqual(caught.exception.kind, "provider_refusal")
        response = {"model":"x","output_text":"I refuse to open the door.","usage":{"input_tokens":1,"output_tokens":1}}
        self.assertEqual(NativeClient._parse("openai", response)[0], "I refuse to open the door.")

    def test_incomplete_response_is_malformed_not_refusal_and_keeps_usage(self):
        response = {"status":"incomplete","incomplete_details":{"reason":"max_output_tokens"},"output":[],"usage":{"input_tokens":7,"output_tokens":9}}
        with self.assertRaises(ProviderError) as caught:
            NativeClient._parse("openai", response)
        self.assertEqual(caught.exception.kind, "output_limit")
        self.assertFalse(caught.exception.billing_uncertain)
        self.assertEqual(caught.exception.payload["usage"], {"input_tokens":7,"cached_input_tokens":0,"output_tokens":9,"reasoning_tokens":0})

    def test_refusal_usage_is_canonical_across_native_provider_shapes(self):
        shapes = [
            ("openai", {"output":[{"type":"message","content":[{"type":"refusal","refusal":"blocked"}]}],
                         "usage":{"input_tokens":7,"input_tokens_details":{"cached_tokens":2},"output_tokens":9}},
             {"input_tokens":7,"cached_input_tokens":2,"output_tokens":9,"reasoning_tokens":0}),
            ("google", {"promptFeedback":{"blockReason":"SAFETY"},
                         "usageMetadata":{"promptTokenCount":7,"cachedContentTokenCount":2,"candidatesTokenCount":6,"thoughtsTokenCount":3}},
             {"input_tokens":7,"cached_input_tokens":2,"output_tokens":9,"reasoning_tokens":3}),
            ("anthropic", {"stop_reason":"refusal","usage":{"input_tokens":5,"cache_read_input_tokens":1,"cache_creation_input_tokens":1,"output_tokens":9}},
             {"input_tokens":7,"cached_input_tokens":1,"cache_write_input_tokens":1,"output_tokens":9,"reasoning_tokens":0}),
        ]
        for provider, response, expected in shapes:
            with self.subTest(provider=provider):
                with self.assertRaises(ProviderError) as caught: NativeClient._parse(provider, response)
                self.assertEqual(caught.exception.kind, "provider_refusal")
                self.assertFalse(caught.exception.billing_uncertain)
                self.assertEqual(caught.exception.payload["usage"], expected)

    def test_google_stream_refusal_usage_is_canonical(self):
        lines = [b'data: {"promptFeedback":{"blockReason":"SAFETY"},"candidates":[{"finishReason":"SAFETY"}],"usageMetadata":{"promptTokenCount":7,"cachedContentTokenCount":2,"candidatesTokenCount":6,"thoughtsTokenCount":3}}\n']
        transport = FakeStreamingTransport(lines)
        profile = self.profile("google", model="gemini-3.7-flash")
        with self.assertRaises(ProviderError) as caught:
            NativeClient({"TEST_KEY":"key"}, transport).generate(profile, [], 20)
        self.assertEqual(caught.exception.kind, "provider_refusal")
        self.assertFalse(caught.exception.billing_uncertain)
        self.assertEqual(caught.exception.payload["usage"], {"input_tokens":7,"cached_input_tokens":2,"output_tokens":9,"reasoning_tokens":3})

    def test_google_stream_prompt_feedback_block_without_candidates_is_final_refusal(self):
        line = b'data: {"promptFeedback":{"blockReason":"SAFETY"},"usageMetadata":{"promptTokenCount":7,"cachedContentTokenCount":2,"candidatesTokenCount":6,"thoughtsTokenCount":3}}\n'
        with self.assertRaises(ProviderError) as caught:
            NativeClient({"TEST_KEY":"key"}, FakeStreamingTransport([line])).generate(
                self.profile("google", model="gemini-3.7-flash"), [], 20)
        self.assertEqual(caught.exception.kind, "provider_refusal")
        self.assertFalse(caught.exception.billing_uncertain)
        self.assertEqual(caught.exception.payload["usage"], {"input_tokens":7,"cached_input_tokens":2,"output_tokens":9,"reasoning_tokens":3})

    def test_output_limit_is_uniform_across_provider_shapes(self):
        shapes = [
            ("openai", {"status":"incomplete","incomplete_details":{"reason":"max_output_tokens"},
                         "usage":{"input_tokens":7,"output_tokens":9}}),
            ("google", {"candidates":[{"finishReason":"MAX_TOKENS","content":{"parts":[{"text":"partial"}]}}],
                         "usageMetadata":{"promptTokenCount":7,"candidatesTokenCount":6,"thoughtsTokenCount":3}}),
            ("anthropic", {"stop_reason":"max_tokens","content":[{"type":"text","text":"partial"}],
                            "usage":{"input_tokens":7,"output_tokens":9}}),
        ]
        for provider, response in shapes:
            with self.subTest(provider=provider), self.assertRaises(ProviderError) as caught:
                NativeClient._parse(provider, response)
            self.assertEqual(caught.exception.kind, "output_limit")
            self.assertFalse(caught.exception.billing_uncertain)
            self.assertEqual(caught.exception.payload["usage"]["input_tokens"], 7)

    def test_google_stream_output_limit_keeps_canonical_usage(self):
        lines = [b'data: {"candidates":[{"finishReason":"MAX_TOKENS","content":{"parts":[{"text":"partial"}]}}],"usageMetadata":{"promptTokenCount":7,"candidatesTokenCount":6,"thoughtsTokenCount":3}}\n']
        transport = FakeStreamingTransport(lines)
        profile = self.profile("google", model="gemini-3.7-flash")
        with self.assertRaises(ProviderError) as caught:
            NativeClient({"TEST_KEY":"key"}, transport).generate(profile, [], 20)
        self.assertEqual(caught.exception.kind, "output_limit")
        self.assertFalse(caught.exception.billing_uncertain)
        self.assertEqual(caught.exception.payload["usage"]["output_tokens"], 9)

    def test_typesafe_cannot_be_used_as_candidate_text_generator(self):
        fake = FakeTransport({})
        profile = self.profile("typesafe", model="jev-1.13.0")
        with self.assertRaises(ProviderError): NativeClient({"TEST_KEY":"secret"}, fake).generate(profile, [], 10)
        self.assertEqual(fake.calls, [])

    def test_http_redirect_is_not_followed(self):
        state = {}
        class FakeOpener:
            def open(self, request, timeout=None):
                handler = state["handler"]()
                state["redirect_request"] = handler.redirect_request(request, None, 307, "Redirect", {"Location":"https://attacker.example"}, "https://attacker.example")
                raise urllib.error.HTTPError(request.full_url, 307, "Redirect", {"Location":"https://attacker.example"}, io.BytesIO(b"{}"))
        def build_opener(handler):
            state["handler"] = handler
            return FakeOpener()
        with patch("urllib.request.build_opener", side_effect=build_opener):
            status, body = _UrllibTransport().post("https://api.openai.com/v1/responses", {"Authorization":"Bearer key"}, b"{}")
        self.assertEqual(status, 307)
        self.assertEqual(body, b"{}")
        self.assertIsNone(state["redirect_request"])


if __name__ == "__main__": unittest.main()
