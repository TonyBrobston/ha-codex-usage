# Authentication recovery

A subscription-session token can be rejected before its JWT expiry. Previously,
usage HTTP 401 retried with the account header, then immediately raised an
authentication failure; OAuth refresh ran only near JWT expiry.

This fork refreshes after both initial account-header attempts return 401, even
with a future JWT expiry. HTTP 401 itself identifies rejected authentication;
response bodies, including `token_expired`, are deliberately not logged. The
known account header is included on the single request after recovery. Another
401 raises `ConfigEntryAuthFailed`; there is no second recovery loop. HTTP 403
and 429 remain ordinary update failures and do not trigger refresh.

- Proactive refresh retains the existing 120-second expiry margin.
- A coordinator lock serializes refresh and re-reads stored credentials. A
  concurrent rejection of an older token reuses the replacement credentials.
- Embedded tokens persist through `async_update_entry`; rotated refresh and ID
  tokens replace previous values, while omitted replacements retain them.
- File-based authentication retains its auth.json persistence behavior.
- Invalid/revoked refresh credentials and missing refresh tokens require reauth.
  Network failures, timeouts, malformed refresh responses, and transient server
  failures remain retryable update errors. Sensitive response bodies are omitted.
- Upstream's reauth flow updates and reloads the existing entry. No entry version,
  domain, sensor/calendar definitions, entity unique IDs, or platforms change.
  Missing five-hour or weekly windows keep their existing `None` normalization;
  plan and credits remain available. Banked-reset failure stays independent.

Baseline: upstream `70ebf87e6df76e031f214492efab490fbdd39403` already contains
[entry-preserving reauth](https://github.com/daddyparodz/ha-codex-usage/pull/31).
Upstream HEAD reports `0.3.0-beta.7` and has no tags or published releases as
inspected on 2026-10-18. Therefore that installed version string cannot establish
whether the installation contains the latest reauth commit. No running files
were inspected or changed. No existing upstream forced-refresh fix was found.
This fork is `0.3.0-beta.8`.

The subscription upgrade as the cause of session invalidation remains a
hypothesis. Mocked tests do not establish that the live OAuth endpoint accepts
Tony's refresh token. After deployment, verify recovery or complete the Home
Assistant reauthentication prompt under Settings → Devices & services. Do not
delete the integration. Reauthentication uses the existing device-code or token
method and preserves the entry and entity registry.

Home Assistant references:
- [Reauthentication](https://contributors.home-assistant.io/core/integrations/reauth-reconfigure/)
- [Config-flow helpers](https://developers.home-assistant.io/blog/2024/10/21/reauth-reconfigure-helpers/)
