# Verified multi-provider dispatch

The agent's chat-completion path now uses a provider-neutral OpenAI-compatible dispatcher. It can order configured AvalAI, OpenRouter, FreeLLMAPI and Gemini adapters and retries only transient network failures and HTTP 408/425/429/5xx statuses. Non-retryable 4xx responses stop immediately. Usage is recorded with the actual provider name.

## Zero-cost enforcement remains authoritative
A configured provider, an environment variable such as `*_COST_CLASS=free`, or a model name is not proof of zero price. Every attempt must match an exact provider/model pair in the trusted evidence map. The live agent currently builds that map only from the authenticated AvalAI model catalog with explicit zero input/output prices and chat capability.

Consequently:
- AvalAI may fail over across eligible catalog-confirmed-free models.
- OpenRouter, FreeLLMAPI and Gemini remain blocked unless an independently verified exact-model zero-price evidence source is added and tested.
- A paid, unknown-price, unlisted or non-chat model is never used as fallback.
- A requested model is subject to the same exact evidence check.
- One internal quota reservation covers the attempt sequence and is finalized once on success or cancelled on failure.

## Adapter compatibility
The current adapters use the OpenAI-compatible `/chat/completions` contract. Provider-specific non-compatible APIs and non-chat surfaces require separate adapters and contract tests. The generic adapter must not be interpreted as proof that every provider's account, model or endpoint is currently available.

## Production boundary
No provider secrets or Railway settings are changed by this PR. No additional provider is activated. Provider/model eligibility depends on runtime evidence, not operator-declared cost labels.
