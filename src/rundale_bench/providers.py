"""Small, native-API-only adapters for benchmark generation."""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class ProviderResponse:
    text: str
    usage: dict[str, int]
    model: str
    elapsed_ms: float
    ttft_ms: float | None
    raw: dict[str, Any]


class ProviderError(Exception):
    def __init__(self, message: str, *, kind: str, status: int | None = None,
                 billing_uncertain: bool = False, payload: dict | None = None):
        super().__init__(message)
        self.kind, self.status = kind, status
        self.billing_uncertain = billing_uncertain
        self.payload = _redact(payload or {})


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: ("[REDACTED]" if str(k).lower() in {"key", "api_key", "authorization", "token", "secret"} else _redact(v)) for k, v in value.items()}
    if isinstance(value, list): return [_redact(v) for v in value]
    return value


def _redact_secret(value: Any, secret: str) -> Any:
    if not secret: return value
    if isinstance(value, dict): return {k: _redact_secret(v, secret) for k, v in value.items()}
    if isinstance(value, list): return [_redact_secret(v, secret) for v in value]
    if isinstance(value, str): return value.replace(secret, "[REDACTED]")
    return value


def _line_text(line: bytes | str) -> str:
    return line.decode("utf-8", "replace").rstrip("\r\n") if isinstance(line, bytes) else line.rstrip("\r\n")


def _line_bytes(line: bytes | str) -> bytes:
    return line if isinstance(line, bytes) else line.encode("utf-8")


def load_profiles(path: Path) -> dict[str, dict]:
    data = json.loads(Path(path).read_text())
    return {p["id"]: p for p in data["profiles"]}


_REASONING_ORDER = ["none", "minimal", "low", "medium", "high", "xhigh", "max"]


def resolve_profile(model: str, reasoning: str | None = None, registry: dict | None = None) -> dict:
    profiles = registry if registry is not None else load_profiles(Path(__file__).parents[2] / "config/providers.json")
    matches = [p for p in profiles.values() if p["model"] == model]
    if not matches:
        raise ValueError(f"Unknown model profile: {model}")
    matches = [p for p in matches if p.get("enabled", True)]
    if not matches:
        raise ValueError(f"Model profile {model} is disabled: {profiles[next(k for k, p in profiles.items() if p['model'] == model)].get('model_status', 'disabled')}")
    if reasoning is not None:
        matches = [p for p in matches if p.get("reasoning") == reasoning]
        if not matches: raise ValueError(f"Unsupported reasoning capability {reasoning!r} for {model}")
    else:
        matches.sort(key=lambda p: _REASONING_ORDER.index(p["reasoning"]) if p.get("reasoning") in _REASONING_ORDER else -1, reverse=True)
    return dict(matches[0])


_HOSTS = {"openai": "api.openai.com", "google": "generativelanguage.googleapis.com",
          "anthropic": "api.anthropic.com", "typesafe": "api.typesafe.ai", "deepseek": "api.deepseek.com"}


class _UrllibTransport:
    def post(self, url: str, headers: dict, body: bytes, timeout: float = 180) -> tuple[int, bytes]:
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            class NoRedirect(urllib.request.HTTPRedirectHandler):
                def redirect_request(self, req, fp, code, msg, headers, newurl):
                    return None
            opener = urllib.request.build_opener(NoRedirect)
            with opener.open(req, timeout=timeout) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            try: return exc.code, exc.read()
            finally: exc.close()
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ProviderError("Provider transport failed", kind="transport", billing_uncertain=True) from exc

    def stream_post(self, url: str, headers: dict, body: bytes, timeout: float = 180):
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None
        opener = urllib.request.build_opener(NoRedirect)
        try:
            return _UrllibStream(opener.open(req, timeout=timeout))
        except urllib.error.HTTPError as exc:
            return _UrllibStream(exc, status=exc.code)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ProviderError("Provider streaming transport failed", kind="transport", billing_uncertain=True) from exc


class _UrllibStream:
    def __init__(self, response, status: int | None = None):
        self.response = response
        self.status = status if status is not None else response.status

    def __enter__(self): return self
    def __exit__(self, *exc): self.close()
    def __iter__(self): return iter(self.response)
    def close(self): self.response.close()


class NativeClient:
    def __init__(self, credentials: dict[str, str] | None = None, transport=None):
        self.credentials = credentials or {}
        self.transport = transport or _UrllibTransport()

    def _key(self, profile: dict) -> str:
        env = profile.get("api_key_env")
        key = self.credentials.get(env) or (os.environ.get(env) if env else None)
        if not key: raise ProviderError("Provider credential is missing", kind="auth", billing_uncertain=False)
        return key

    def generate(self, profile: dict, messages: list[dict], max_output_tokens: int,
                 response_schema: dict | None = None) -> ProviderResponse:
        provider = profile["provider"]
        if provider not in _HOSTS: raise ProviderError("Unsupported provider", kind="malformed")
        if provider == "typesafe":
            raise ProviderError("TypeSafe Jev is a structured judge API, not a text generation API", kind="malformed")
        base = profile.get("base_url", f"https://{_HOSTS[provider]}")
        parsed = urllib.parse.urlparse(base)
        if parsed.scheme != "https" or parsed.hostname != _HOSTS[provider] or parsed.port not in (None, 443):
            raise ProviderError("Provider endpoint is outside the native API allowlist", kind="malformed")
        key = self._key(profile)
        body, url, headers = self._request(profile, messages, max_output_tokens, response_schema, key, base.rstrip("/"))
        if provider == "google" and callable(getattr(self.transport, "stream_post", None)):
            stream_url = url.replace(":generateContent", ":streamGenerateContent", 1) + "?alt=sse"
            return self._generate_google_stream(profile, body, stream_url, headers, key)
        start = time.monotonic()
        try:
            status, raw_bytes = self.transport.post(url, headers, json.dumps(body).encode(), timeout=180)
        except ProviderError: raise
        except Exception as exc:
            raise ProviderError("Provider transport failed", kind="transport", billing_uncertain=True) from exc
        elapsed = (time.monotonic() - start) * 1000
        try: data = json.loads(raw_bytes)
        except Exception as exc:
            raise ProviderError("Provider returned malformed JSON", kind="malformed", status=status,
                                billing_uncertain=status < 400) from exc
        safe = _redact_secret(_redact(data), key)
        if status >= 300:
            kind = "auth" if status in (401, 403) else "provider_refusal" if status == 400 and _is_refusal(data) else "provider"
            raise ProviderError("Provider returned an error", kind=kind, status=status,
                                billing_uncertain=status >= 500 or 300 <= status < 400, payload=safe)
        try:
            text, usage = self._parse(provider, data)
        except ProviderError as exc:
            exc.payload = _redact_secret(exc.payload, key)
            raise
        except Exception as exc:
            raise ProviderError("Provider response has an unsupported shape", kind="malformed", status=status,
                                billing_uncertain=True, payload=safe) from exc
        return ProviderResponse(_redact_secret(text, key), usage, data.get("model", profile["model"]), elapsed, None, safe)

    def _generate_google_stream(self, profile: dict, body: dict, url: str, headers: dict, key: str) -> ProviderResponse:
        start = time.monotonic()
        raw_chunks: list[str] = []
        visible: list[str] = []
        final_usage: dict | None = None
        prompt_feedback: dict = {}
        finish_reason: str | None = None
        model = profile["model"]
        ttft_ms: float | None = None
        try:
            stream = self.transport.stream_post(url, headers, json.dumps(body).encode(), timeout=180)
            with stream as response:
                if response.status >= 300:
                    body_text = b"".join(_line_bytes(line) for line in response).decode("utf-8", "replace")
                    try: error_data = json.loads(body_text)
                    except json.JSONDecodeError: error_data = {"body": body_text}
                    safe_error = _redact_secret(_redact(error_data), key)
                    status = response.status
                    kind = "auth" if status in (401, 403) else "provider_refusal" if status == 400 and _is_refusal(error_data) else "provider"
                    raise ProviderError("Provider returned an error", kind=kind, status=status,
                                        billing_uncertain=status >= 500 or 300 <= status < 400,
                                        payload={"raw": safe_error, "chunks": []})
                for line in response:
                    line_text = _line_text(line)
                    if not line_text or line_text.startswith(":") or not line_text.startswith("data:"):
                        continue
                    event_text = line_text[5:].strip()
                    if not event_text or event_text == "[DONE]":
                        continue
                    raw_chunks.append(event_text)
                    try: event = json.loads(event_text)
                    except json.JSONDecodeError as exc:
                        raise ProviderError("Gemini stream contained malformed JSON", kind="malformed", billing_uncertain=True,
                                            payload={"chunks": raw_chunks}) from exc
                    if isinstance(event.get("usageMetadata"), dict):
                        final_usage = event["usageMetadata"]
                    if isinstance(event.get("promptFeedback"), dict):
                        prompt_feedback = event["promptFeedback"]
                    model = event.get("modelVersion", event.get("model", model))
                    for candidate in event.get("candidates", []):
                        if candidate.get("index", 0) == 0:
                            finish_reason = candidate.get("finishReason", finish_reason)
                            parts = candidate.get("content", {}).get("parts", [])
                            for part in parts:
                                text = part.get("text")
                                if isinstance(text, str) and text and not part.get("thought", False):
                                    if ttft_ms is None:
                                        ttft_ms = (time.monotonic() - start) * 1000
                                    visible.append(text)
        except ProviderError as exc:
            exc.payload = _redact_secret({**exc.payload, "chunks": raw_chunks,
                                          "usage": final_usage or {}}, key)
            raise
        except Exception as exc:
            elapsed = (time.monotonic() - start) * 1000
            raise ProviderError("Provider streaming transport failed", kind="transport", billing_uncertain=True,
                                payload={"chunks": _redact_secret(raw_chunks, key), "partial_text": _redact_secret("".join(visible), key),
                                         "usage": _redact_secret(final_usage or {}, key), "elapsed_ms": elapsed}) from exc
        elapsed = (time.monotonic() - start) * 1000
        raw = {"modelVersion": model, "promptFeedback": prompt_feedback,
               "candidates": [{"index": 0, "finishReason": finish_reason,
                               "content": {"parts": [{"text": "".join(visible)}]}}],
               "usageMetadata": final_usage or {}, "stream_chunks": raw_chunks}
        safe = _redact_secret(_redact(raw), key)
        try:
            text, usage = self._parse("google", raw)
        except ProviderError as exc:
            exc.payload = _redact_secret({"raw": safe, "usage": final_usage or {}, "chunks": raw_chunks}, key)
            raise
        return ProviderResponse(_redact_secret(text, key), usage, model, elapsed, ttft_ms, safe)

    @staticmethod
    def _request(profile, messages, limit, schema, key, base):
        provider, model = profile["provider"], profile["model"]
        if provider == "openai":
            body = {"model": model, "input": messages, "max_output_tokens": limit}
            effort = profile.get("reasoning")
            if effort and effort != "none": body["reasoning"] = {"effort": effort}
            if schema: body["text"] = {"format": {"type": "json_schema", "name": "judge_result", "strict": True, "schema": schema}}
            return body, base + "/v1/responses", {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        if provider == "google":
            sys = "\n".join(m["content"] for m in messages if m["role"] in ("system", "developer"))
            contents = [{"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]} for m in messages if m["role"] not in ("system", "developer")]
            cfg = {"maxOutputTokens": limit}
            if profile.get("reasoning") not in (None, "none"):
                cfg["thinkingConfig"] = {"thinkingLevel": profile["reasoning"]}
            if schema: cfg.update({"responseMimeType": "application/json", "responseSchema": schema})
            body = {"contents": contents, "generationConfig": cfg}
            if sys: body["systemInstruction"] = {"parts": [{"text": sys}]}
            return body, base + f"/v1beta/models/{urllib.parse.quote(model, safe='')}:generateContent", {"x-goog-api-key": key, "Content-Type": "application/json"}
        if provider == "anthropic":
            sys = "\n".join(m["content"] for m in messages if m["role"] in ("system", "developer"))
            body = {"model": model, "max_tokens": limit, "messages": [{"role": m["role"], "content": m["content"]} for m in messages if m["role"] in ("user", "assistant")]}
            if sys: body["system"] = sys
            if profile.get("reasoning") not in (None, "none"): body["output_config"] = {"effort": profile["reasoning"]}
            if schema:
                body["output_config"] = {**body.get("output_config", {}), "format": {"type": "json_schema", "schema": schema}}
            return body, base + "/v1/messages", {"x-api-key": key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"}
        if provider == "typesafe":
            raise ProviderError("TypeSafe Jev supports structured judgments, not text generation", kind="malformed")
        # DeepSeek exposes OpenAI-compatible chat completions.
        body = {"model": model, "messages": messages, "max_tokens": limit}
        return body, base + "/v1/chat/completions", {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    def _post_typesafe(self, profile: dict, state: dict, questions: dict) -> dict:
        base = profile.get("base_url", "https://api.typesafe.ai").rstrip("/")
        parsed = urllib.parse.urlparse(base)
        if parsed.scheme != "https" or parsed.hostname != "api.typesafe.ai" or parsed.port not in (None, 443):
            raise ProviderError("Provider endpoint is outside the native API allowlist", kind="malformed")
        key = self._key(profile)
        payload = {"model": profile["model"], "state": state, "questions": questions}
        try:
            status, raw = self.transport.post(base + "/v1/systemone", {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, json.dumps(payload).encode(), timeout=180)
        except ProviderError: raise
        except Exception as exc: raise ProviderError("Provider transport failed", kind="transport", billing_uncertain=True) from exc
        try: data = json.loads(raw)
        except Exception as exc: raise ProviderError("Provider returned malformed JSON", kind="malformed", status=status, billing_uncertain=status < 400) from exc
        if status >= 400:
            raise ProviderError("Provider returned an error", kind="auth" if status in (401,403) else "provider", status=status, billing_uncertain=status >= 500, payload=_redact_secret(_redact(data), key))
        return _redact_secret(_redact(data), key)

    @staticmethod
    def _parse(provider, data):
        if provider == "openai":
            if any(o.get("type") == "refusal" for o in data.get("output", [])):
                raise _provider_result_error("Provider refused the request", "provider_refusal", data, data.get("usage", {}))
            if data.get("status") == "incomplete":
                u = data.get("usage", {})
                usage_known = type(u.get("input_tokens")) is int and type(u.get("output_tokens")) is int
                raise ProviderError("Provider response was incomplete", kind="malformed", billing_uncertain=not usage_known,
                                    payload={"raw": _redact(data), "usage": _redact(u)})
            text = data.get("output_text") or "".join(c.get("text", "") for o in data.get("output", []) for c in o.get("content", []) if c.get("type") == "output_text")
            u = data.get("usage", {}); det = u.get("input_tokens_details", {})
            usage = {"input_tokens": u.get("input_tokens"), "cached_input_tokens": det.get("cached_tokens", 0), "output_tokens": u.get("output_tokens"), "reasoning_tokens": u.get("output_tokens_details", {}).get("reasoning_tokens", 0)}
        elif provider == "google":
            if data.get("promptFeedback", {}).get("blockReason") or not data.get("candidates") or data["candidates"][0].get("finishReason") in {"SAFETY", "BLOCKLIST", "PROHIBITED_CONTENT"}:
                raise _provider_result_error("Provider refused the request", "provider_refusal", data, data.get("usageMetadata", {}))
            text = "".join(p.get("text", "") for p in data["candidates"][0].get("content", {}).get("parts", []))
            u = data.get("usageMetadata", {}); thoughts = u.get("thoughtsTokenCount")
            candidates = u.get("candidatesTokenCount")
            usage = {"input_tokens": u.get("promptTokenCount"), "cached_input_tokens": u.get("cachedContentTokenCount", 0),
                     # Google bills reasoning/thought tokens as output; the separate
                     # reasoning field is a subset used for analysis, not additive.
                     "output_tokens": candidates + thoughts if isinstance(candidates, int) and isinstance(thoughts, int) else None,
                     "reasoning_tokens": thoughts}
        elif provider == "anthropic":
            if data.get("stop_reason") == "refusal": raise _provider_result_error("Provider refused the request", "provider_refusal", data, data.get("usage", {}))
            text = "".join(c.get("text", "") for c in data.get("content", []) if c.get("type") == "text")
            u = data.get("usage", {}); cache_read = u.get("cache_read_input_tokens", 0); cache_write = u.get("cache_creation_input_tokens", 0)
            usage = {"input_tokens": u.get("input_tokens") + cache_read + cache_write if isinstance(u.get("input_tokens"), int) and isinstance(cache_read, int) and isinstance(cache_write, int) else None,
                     "cached_input_tokens": cache_read, "cache_write_input_tokens": cache_write,
                     "output_tokens": u.get("output_tokens"), "reasoning_tokens": 0}
        elif provider == "typesafe":
            answers = data.get("answers", {})
            ans = answers.get("answer", {}) if isinstance(answers, dict) else {}
            text = ans.get("answer", ans.get("choice", "")) if isinstance(ans, dict) else str(ans)
            usage = {"input_tokens": data.get("usage", {}).get("input_tokens"), "cached_input_tokens": 0, "output_tokens": data.get("usage", {}).get("output_tokens"), "reasoning_tokens": 0}
        else:
            choice = data["choices"][0]; text = choice["message"].get("content", "")
            u = data.get("usage", {}); usage = {"input_tokens": u.get("prompt_tokens"), "cached_input_tokens": u.get("prompt_tokens_details", {}).get("cached_tokens", 0), "output_tokens": u.get("completion_tokens"), "reasoning_tokens": u.get("completion_tokens_details", {}).get("reasoning_tokens", 0)}
        if not isinstance(text, str): raise ValueError("text missing")
        if any(not isinstance(usage[k], int) for k in ("input_tokens", "output_tokens")):
            metering = data.get("usage", data.get("usageMetadata", {}))
            raise ProviderError("Usage metadata is missing; billing is uncertain", kind="malformed", billing_uncertain=True,
                                payload={"raw": _redact(data), "usage": _redact(metering)})
        usage["cached_input_tokens"] = int(usage["cached_input_tokens"] or 0)
        usage["reasoning_tokens"] = int(usage["reasoning_tokens"] or 0)
        return text, usage


def _is_refusal(data):
    error = data.get("error", {}) if isinstance(data, dict) else {}
    code = str(error.get("code", "")).lower() if isinstance(error, dict) else ""
    typ = str(error.get("type", "")).lower() if isinstance(error, dict) else ""
    return code in {"content_filter", "safety", "refusal", "blocked", "prompt_blocked"} or typ in {"content_filter", "safety_violation", "refusal"} or bool(data.get("promptFeedback", {}).get("blockReason"))


def _provider_result_error(message: str, kind: str, raw: dict, usage: dict) -> ProviderError:
    input_key = "promptTokenCount" if "usageMetadata" in raw else "input_tokens"
    output_key = "candidatesTokenCount" if input_key == "promptTokenCount" else "output_tokens"
    known = type(usage.get(input_key)) is int and type(usage.get(output_key)) is int
    if input_key == "promptTokenCount": known = known and type(usage.get("thoughtsTokenCount")) is int
    return ProviderError(message, kind=kind, billing_uncertain=not known,
                         payload={"raw": _redact(raw), "usage": _redact(usage)})
