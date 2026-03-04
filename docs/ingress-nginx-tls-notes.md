# ingress-nginx TLS / certificate notes

## Fixed in repo

- **iam/keycloak-tls**: Certificate resource added (`apps/iam/overlays/dev/certificate-keycloak-tls.yaml`) so cert-manager issues a cert with SAN `iam.dev.sandbox.internal.nbank.fr`. The IAM overlay uses this instead of the Kustomize secretGenerator.
- **kyc/headlessexample**: Ingress disabled when `headlessexample.enabled: false` so the controller stops looking for the missing Service.

## Remaining “certificate not found” warnings

These mean the **Secret** referenced by the Ingress does not exist (yet) in that namespace:

| Namespace      | Secret name              | Action |
|----------------|--------------------------|--------|
| kyc            | nbank                    | Create a Certificate (or Secret) in `kyc` for `*.dev.sandbox.internal.nbank.fr` or the specific KYC hostnames, using ClusterIssuer `nbank-dev`. |
| app            | nexus-bank-api-dev-tls   | Ensure cert-manager can complete HTTP-01 for the Ingress host; or add an explicit Certificate with this `secretName`. |
| api            | cbanking-api-dev-tls     | Same as above for the API ingress host. |
| core-banking   | core-banking-tls         | Same; Certificate or ensure ingress annotation triggers issuance. |
| core-banking   | hooks-api-dev-tls        | Same for hooks-api host. |

Until those Secrets exist, ingress-nginx uses its **default certificate** for those hosts (often causing browser cert warnings). After cert-manager creates the Secrets (or you create them manually), the warnings go away and the correct certs are served.
