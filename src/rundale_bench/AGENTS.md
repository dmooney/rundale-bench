# Native provider accounting

Usage from an earlier streaming chunk is not a final bill, even when every token
field is present. Any abnormal stream termination must retain uncertain billing;
only a completed stream or a complete provider error body can settle final usage.
Normalize native metering through the same helper on success and failure paths.
