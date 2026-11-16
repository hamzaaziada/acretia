# MeshPool gateway: image generation workaround (2026-11-16)

Result: **no working route found.** 10 live calls of the 15 budgeted; total spend about $0.003
(`x-litellm-key-spend` 8.5251 -> 8.5283). Key read from the Keychain, sent only to `llm.meshpool.ai`, never logged.
No provider was written (`om/meshpool_images.py` not created): nothing returns image bytes.

## Call log (prompt: small flat bar-chart illustration; low quality, 1024x1024 where accepted)

| # | Route | Model | Status | Shape |
|---|-------|-------|--------|-------|
| 1 | POST /v1/chat/completions | gpt-image-2 | 400 | `{"error":{"message":"The request was rejected as invalid. (reference: ...)","code":"400"}}` |
| 2 | same + `modalities:["image","text"]` | gpt-image-2 | 400 | same |
| 3 | POST /v1/responses `input` | gpt-image-2 | 400 | same |
| 4 | POST /v1/responses + `tools:[image_generation]` | gpt-6.1-terra | 200 | output = reasoning item only, no `image_generation_call` |
| 5 | POST /v1/chat/completions + `tools:[image_generation]` | gpt-6.1-terra | 200 | `finish_reason: length`, empty content, redacted thinking only |
| 6 | chat + `modalities` | gpt-6.1-terra | 200 | same as 5 (modalities ignored) |
| 7 | POST /v1/images/edits | gpt-image-2 | 404 | `gateway_path_not_exposed` |
| 8 | POST /images/generations (no /v1) | gpt-image-2 | 404 | `gateway_path_not_exposed` |
| 9 | chat + `modalities` | grok-4.7 | 200 | `finish_reason: length`, empty content, redacted thinking only |
| 10 | POST /v1/responses, `tool_choice` forced to image_generation, max_output_tokens 3000 | gpt-6.1-terra | 200 | `tools: []` echoed back; output = reasoning + a 501-char text message, no image item |

## Findings

- [OBSERVATION] `/v1/images/generations`, `/v1/images/edits` and `/images/generations` return 404 `gateway_path_not_exposed`: "Only inference and usage endpoints are available on this host."
- [OBSERVATION] `gpt-image-2` is listed by `/v1/models` but is rejected with a generic 400 on both `/v1/chat/completions` and `/v1/responses` (calls 1-3).
- [OBSERVATION] With a gpt-6.1-terra request carrying `tools:[{"type":"image_generation"}]`, the response echoes `tools: []` (call 10). No image item was produced even with a forced `tool_choice`.
- [INFERENCE] The gateway (LiteLLM-style, `x-litellm-key-spend` header) strips the hosted `image_generation` tool and `modalities`, so the earlier "invalid or stripped" note holds. A reasoning model then answers in text.
- [INFERENCE] The 400 on gpt-image-2 probably comes from the gateway or upstream refusing a non-image endpoint for an image-only model; the body gives no detail, so the exact cause is [UNKNOWN].
- [UNKNOWN] Not tried: gpt-5.6-* / gpt-6-luna with the tool, meshpool-* models, `/v1/chat/completions` with other image models. Calls 4-6 and 10 give no reason to expect different handling of the same stripped tool.
- [UNKNOWN] Call 10's 501-char text reply was not inspected, so whether it contained a data URI or URL is unconfirmed (no `data:image` or `b64_json` string matched in call 1-9 scans).

## What the gateway would need

Any one of: expose `POST /v1/images/generations` (and `/edits`) on llm.meshpool.ai; or pass the Responses `image_generation` tool through to an image-capable upstream and return `image_generation_call.result` base64; or accept `gpt-image-2` on `/v1/responses`. Until then decks stay on the SVG designer.
