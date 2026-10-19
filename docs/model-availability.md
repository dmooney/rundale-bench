# Launch candidate availability

The launch plan names Gemini 3.5 Flash-Lite and Gemini 3.7 Flash at their highest
supported reasoning settings. An alias that returns a replacement model cannot
supply an independently labelled result for the historical model.

## Gemini 3.7 Flash: unavailable as requested

Checked October 18, 2026. Google's [model page](https://ai.google.dev/gemini-api/docs/models/gemini-3.7-flash)
and [deprecation table](https://ai.google.dev/gemini-api/docs/deprecations), both
updated October 12, state that generation requests using `gemini-3.7-flash` go
to Gemini 3.8 Flash. The retained 3.7 benchmark profile remains disabled. No
replacement was run and no model-quality score is assigned.

The native metadata GET still returned HTTP 200 and a historical 3.7 card.
Metadata availability is therefore insufficient to establish generation identity.
No generation request was made; the routing conclusion is based on the provider's
documentation, not a newly observed generated response.

The [availability record](../availability/3.0/gemini-3.7-flash.json) and
[public model metadata](../availability/3.0/gemini-3.7-flash-metadata.json) retain
the check time and provenance. This is the second launch candidate's documented
setup outcome, not a completed benchmark or a fabricated inference DNF. It adds
no leaderboard result. Testing Gemini 3.8 would require an explicitly named new
profile and run.

## Gemini 3.5 Flash-Lite: baseline incomplete

The first attempt, `5e2177f168e2`, stopped before receiving any model output.
[Issue #3](https://github.com/dmooney/rundale-bench/issues/3) tracks its network
diagnosis and unresolved billing. A non-generating metadata check showed the
exact native model remains available, but neither metadata nor the failed run
provides a quality score. A completed baseline is still required.
