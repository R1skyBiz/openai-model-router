# Live verification evidence — 2026-09-07

Status: **BLOCKED — no OpenAI credential available; no live call made.**
Actual spend: **$0**. Account access, live classifier quality and end-to-end live success are unverified. Offline guards and mock canaries are not access evidence.

The root checked the process environment and repository `.env`/`.env.local` presence without displaying any secret. No key was found. No key was created or searched for outside this project.

## Public facts reviewed

Official model pages were retrieved on 2026-09-07. Standard short-context input / cache-read / output USD per million tokens agree with the immutable 2026-09-06 catalog:

| Alias | Provider ID | Input / cache read / output | Official source |
| --- | --- | --- | --- |
| Luna | gpt-5.6-luna | 0.20 / 0.02 / 1.20 | [Luna](https://developers.openai.com/api/docs/models/gpt-5.6-luna) |
| Terra | gpt-5.6-terra | 2.00 / 0.20 / 12.00 | [Terra](https://developers.openai.com/api/docs/models/gpt-5.6-terra) |
| Sol | gpt-5.6-sol | 4.00 / 0.40 / 20.00 | [Sol](https://developers.openai.com/api/docs/models/gpt-5.6-sol) |
| Astra | gpt-6-astra | 10.00 / 1.00 / 50.00 | [Astra](https://developers.openai.com/api/docs/models/gpt-6-astra) |

Cache-write charge is 1.25× uncached input. Luna/Terra/Sol support none/low/medium/high/xhigh/max; Astra supports low/medium/high/xhigh/max. The deliberately small live path excludes long context and hosted tools. Sol's promotional availability statement is not a future replacement tariff. No existing snapshot was changed.

The [Responses create reference](https://developers.openai.com/api/reference/python/resources/responses/methods/create) was retrieved; the adapter uses explicit bounded output/time, standard service tier, `store=false`, disabled truncation and SDK retries disabled. Output cap includes reasoning. The [model retrieval reference](https://developers.openai.com/api/reference/python/resources/models/methods/retrieve) was retrieved for account preflight tooling. Public documentation and model-list/retrieve access do not prove a successful paid Responses invocation.

Live operator tooling must retain immutable verified-on/catalog/pricing evidence, safe response status/usage/cost/latency/IDs and release versions. It requires explicit opt-in plus an aggregate cap. Unknown cost holds the full reservation and stops further calls. Run live verification separately from offline CI. Successful canaries never modify policy.

Account evidence includes `credential_sha256`, a SHA-256 fingerprint of the exact
injected credential used to verify access. Preflight compares it without printing
the credential or fingerprint. Credential rotation invalidates old access evidence
and requires a newly verified immutable document. This is operator evidence, not
a cryptographic attestation by OpenAI.
