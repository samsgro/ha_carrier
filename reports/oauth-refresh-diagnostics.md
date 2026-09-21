# OAuth refresh diagnostics — builder report

Date: 2026-09-21  
Worker: Orca dispatched builder  
Scope: diagnostic forks only. Home Assistant was not restarted or
redeployed. The `home-automation` worktree was not modified.

## Outcome

Both upstream repositories were forked to `samsgro`, checked out at the
requested tags, and given `oauth-refresh-diagnostics` branches.

`carrier_api` now logs secret-safe OAuth refresh diagnostics at the token
response handling point. `ha_carrier` pins that library by immutable
commit and exposes an explicit diagnostic version. No thermostat,
entity, or config-flow behavior changed.

## Forks and commits

| Repo | Upstream tag | Fork | Branch | HEAD SHA |
| --- | --- | --- | --- | --- |
| `carrier_api` | v3.6.0 (`43f9ddcbcbb026ca97333db0c9908751f459bcaf`) | https://github.com/samsgro/carrier_api | `oauth-refresh-diagnostics` | `84295ff294f0c97d7c978ca1ec0062f0587d3418` |
| `ha_carrier` | v2.28.2 (`533a4f471a1e8bcf7d18d6af93651fe240124f37`) | https://github.com/samsgro/ha_carrier | `oauth-refresh-diagnostics` | `438a1b8605d17b43dca49d9c8e5bff09f4d251cc` |

Diagnostic versions:

- `carrier-api==3.6.0+oauthdiag.1`
- `ha_carrier==2.28.2+oauthdiag.1`

Immutable library pin used by `ha_carrier`:

```text
carrier-api @ git+https://github.com/samsgro/carrier_api.git@84295ff294f0c97d7c978ca1ec0062f0587d3418
```

No upstream pull requests were opened.

## What changed in `carrier_api`

New module `src/carrier_api/oauth_refresh_diagnostics.py` builds an
allowlisted record from the refresh HTTP response. `refresh_auth_token`
in `api_connection_graphql.py` emits that record and then raises the
same exceptions as v3.6.0.

Logged fields only:

- HTTP status
- Content-Type
- body class
- body length and SHA-256
- allowlisted OAuth `error` / `error_description`
- allowlisted request IDs: `x-request-id`, `x-correlation-id`,
  `x-okta-request-id`, `x-okta-requestid`, `request-id`

Never logged: username, password, access/refresh tokens, cookies,
request body, `Authorization`, arbitrary headers, or raw response body.
Unsafe `error` / `error_description` values (JWT-like, secret keywords,
non-allowlisted codes) are dropped.

Success refreshes log at DEBUG. Failures log at WARNING. Diagnostic
collection errors are swallowed so they cannot change exception
behavior.

## Tests

`carrier_api` lint, mypy, and pytest were run in a local Python 3.14
venv (`scripts/lint`, `scripts/test`).

```text
ruff check / ruff format / mypy: passed
202 passed in 0.52s
TOTAL coverage 90%
```

Covered refresh cases:

- success + refresh-token rotation
- `invalid_grant` → `CarrierApiAuthError`
- other JSON OAuth error (`temporarily_unavailable`) → `CarrierApiTokenRefreshError`
- HTML challenge
- empty body
- malformed JSON body
- adversarial secret payloads (tokens, JWT `error`, password
  descriptions, `Authorization` / `Cookie` headers)

Existing exception-cause tests still pass.

A clean Python 3.14 virtualenv installed the pinned commit:

```text
installed 3.6.0+oauthdiag.1
const 3.6.0+oauthdiag.1
diag_ok invalid_grant
```

`ha_carrier` changes are version, dependency pin, and documentation
only. Manifest JSON parsed; version matches `const.VERSION`; requirement
contains the 40-character SHA. Full `ha_carrier` pytest was not run
because it needs a Home Assistant install and no integration code paths
changed.

## Changed files

### `carrier_api`

- `README.md`
- `src/carrier_api/api_connection_graphql.py`
- `src/carrier_api/const.py`
- `src/carrier_api/oauth_refresh_diagnostics.py` (new)
- `tests/test_api_connection_graphql.py`
- `tests/test_oauth_refresh_diagnostics.py` (new)

### `ha_carrier`

- `README.md`
- `DIAGNOSTIC_INSTALL.md` (new)
- `pyproject.toml`
- `custom_components/ha_carrier/const.py`
- `custom_components/ha_carrier/manifest.json`
- `reports/oauth-refresh-diagnostics.md` (this file)

## Deployment and rollback

Not deployed. When Sam is ready, follow
`https://github.com/samsgro/ha_carrier/blob/oauth-refresh-diagnostics/DIAGNOSTIC_INSTALL.md`.

Short form:

1. Copy this branch's `custom_components/ha_carrier` into Home Assistant.
2. Restart or repair dependencies so pip installs the git SHA pin.
3. Confirm `carrier-api` version `3.6.0+oauthdiag.1`.
4. Watch for `Carrier OAuth token refresh response` log lines.

Rollback: restore upstream `ha_carrier` v2.28.2 and
`carrier-api==3.6.0` from PyPI, then restart.

## What's left

- Deploy to Home Assistant only when Sam asks.
- No upstream PRs.
- Use the new logs to distinguish `invalid_grant`, HTML challenges, and
  malformed refresh bodies if token refresh fails again.
