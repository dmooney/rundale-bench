# Native provider adapters

`NativeClient` supports OpenAI Responses, Google Gemini `generateContent`, Anthropic
Messages, TypeSafe Jev System One, and the native DeepSeek compatible Chat Completions
endpoint. It uses only the Python standard library. Requests use fixed provider hosts;
custom `base_url` values are accepted only when they retain the provider's canonical
HTTPS hostname. There is no arbitrary router URL support.

Set the selected profile's `api_key_env` variable or pass credentials to
`NativeClient(credentials={"OPENAI_API_KEY": "…"})`. Credentials are never included
in response records or error payloads. `ProviderError.kind` distinguishes transport,
authentication, provider, explicit API refusal, and malformed-response errors. The
adapter does not retry. A transport failure or a malformed response after HTTP 2xx is
marked `billing_uncertain`; callers must not blindly repeat a potentially billed call.

The native Google transport uses `streamGenerateContent` with SSE. `ttft_ms` measures
from request start through receipt and parsing of the first non-empty, non-thought text
part. The complete raw event list and latest final `usageMetadata` are retained in
`ProviderResponse.raw`. A stream interrupted before completion preserves partial chunks
and metering in `ProviderError.payload`, then marks billing uncertain. Other native
providers use non-streaming endpoints and return `ttft_ms: null`; injected transports
without `stream_post` use the non-streaming Google fallback and also return null rather
than estimating TTFT.

Usage normalizes to input, cached input, output, and reasoning tokens. Provider
reasoning tokens are a subset of output tokens. For pricing, count output tokens once:

```text
uncached_input * input_rate + cached_input * cached_input_rate
+ output_tokens * output_rate
```

The Google rate for cached input is null where the Standard tier does not offer input
caching; never estimate it from another tier. A missing input/output usage count makes
the response billing-uncertain. Prices are USD per million tokens and reflect the
Standard tier at profile creation; the Gemini 3.7 Flash introductory rates are stated
by Google to end 2026-12-31. Recheck the linked official price pages before a new
benchmark campaign. A null rate means pricing is not established and must block cost
reservation until updated from an official source.

`resolve_profile` returns a pinned profile snapshot. Request a specific reasoning
level to select that exact snapshot; otherwise it returns the highest registered level
for that model. It rejects unknown models and unavailable levels rather than silently
substituting a capability. Reasoning capability lists follow provider model
documentation. Gemini 3.7 Flash is deprecated and its API name currently routes to
Gemini 3.8 Flash, so its retained profile is disabled to prevent mislabelled runs. Its
introductory pricing is valid through 2026-12-31. The registry includes Gemini 3.5
Flash-Lite, the disabled 3.7 profile, GPT-6.1 Sol max candidate and high judge
snapshots, Jev 1.13.0, and an Anthropic adapter profile with unset reasoning and prices
so cost preflight blocks it.

`judge_response` evaluates one case per request. Numeric judges receive a strict JSON
schema whose axis values are integer grades from 1 through 5, and Jev receives each
full literal anchor under the corresponding grade key. Candidate content is explicitly
treated as untrusted data. The judge returns integer grades plus raw response and
normalized usage for auditable scoring. Invalid judgments retain the paid response
and its usage in the error payload; billing is marked uncertain only when usage is
missing or invalid.

References:

- [OpenAI Responses API](https://platform.openai.com/docs/api-reference/responses)
- [OpenAI API pricing](https://developers.openai.com/api/docs/pricing)
- [Gemini generateContent API](https://ai.google.dev/api/generate-content)
- [Gemini streaming generateContent API](https://ai.google.dev/api/generate-content)
- [Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing)
- [Gemini 3.7 Flash model status](https://ai.google.dev/gemini-api/docs/models/gemini-3.7-flash)
- [Anthropic Messages API](https://docs.anthropic.com/en/api/messages)
- [TypeSafe System One API](https://docs.typesafe.ai/)
