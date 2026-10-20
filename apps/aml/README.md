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

The console uses Keycloak, the same issuer as Fineract: realm `internal` on `https://iam.dev.sandbox.internal.nbank.fr/auth`. Choose **Sign in with OpenID Connect**.

| | |
| --- | --- |
| Email | `aml-admin@nbank.fr` |
| Password | `marble-aml-dev` |

The `marble-init-iam` job creates the Keycloak client `aml` and this user. Same values as the `marble` secret in `apps/aml/base/secret.yaml`.

Marble only shows that button when `license-key` in the secret is a Marble license with the SSO entitlement. Without it, the API exits with `cannot use OpenID Connect configuration without the appropriate license entitlement`.
