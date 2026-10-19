# Native provider accounting

Usage from an earlier streaming chunk is not a final bill, even when every token
field is present. Any abnormal stream termination must retain uncertain billing;
only a completed stream or a complete provider error body can settle final usage.
Normalize native metering through the same helper on success and failure paths.

Gemini may omit a zero `thoughtsTokenCount`. Accept an omitted zero only when
valid final prompt, candidate and total counts prove an exact zero residual,
with no tool-use tokens. Missing or inconsistent totals remain uncertain;
never fill in zero merely because the thoughts field is absent.
