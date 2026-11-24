# KOROUSH-CENTRAL-AI

Private, audit-first GitHub engineering agent. The current repair workflow generates bounded proposals only; it does not write to target repositories or merge changes.

## LLM provider configuration

The existing `LLM_*` configuration remains the default and is preserved. To select AvalAI, set these Railway service variables:

- `LLM_PROVIDER=avalai`
- `AVALAI_BASE_URL=https://api.avalai.ir/v1`
- `AVALAI_API_KEY=<your AvalAI API key>`
- `AVALAI_MODEL=<exact model ID from your AvalAI account/catalog>`

The service calls the OpenAI-compatible `/chat/completions` endpoint. Keep the API key in Railway Variables; never commit it to GitHub or paste it into chat.

To return to the existing provider, set `LLM_PROVIDER=legacy`; the existing `LLM_BASE_URL`, `LLM_API_KEY`, and `LLM_MODEL` values remain available.

After changing Railway variables, redeploy/restart the service and use `/panel` to run the diagnostics check. A successful diagnostic confirms one small live inference request, not every model capability.

Official AvalAI API reference: https://docs.avalai.org/en/api-reference/introduction
