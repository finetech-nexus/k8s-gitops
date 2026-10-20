# Marble (AML)

Decision engine for sanctions screening and transaction checks. Namespace `aml`.

## Console

Open this host exactly. Another host, or the Kong address alone, returns `no Route matched with those values`.

- https://aml-app.dev.sandbox.nbank.fr
- https://aml-app.dev.sandbox.internal.nbank.fr

API:

- https://aml-api.api.dev.sandbox.nbank.fr
- https://aml-api.api.dev.sandbox.internal.nbank.fr

## Login

Sign in with email and password. The browser talks to the Firebase emulator at `https://aml-auth.dev.sandbox.internal.nbank.fr`. The API keeps using the in-cluster Service `marble-firebase`.

| | |
| --- | --- |
| Email | `aml-admin@nbank.fr` |
| Password | `marble-aml-dev` |

Created by the `marble-init` job on an empty database. Same values as the `marble` secret in `apps/aml/base/secret.yaml`.
