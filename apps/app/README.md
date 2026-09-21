# App layer — BFF + Product Studio

Flux deploys namespace `app`:

| App | Image | Ingress |
| --- | --- | --- |
| BFF `nexus-bank-api` | `nexusbank/nexus-bank-api:latest` | `app.api.dev.sandbox.internal.nbank.fr` |
| Product Studio `produit-app` | `nexusbank/produit-app:latest` | `produit-app.dev.sandbox.internal.nbank.fr` |

| Item | Path |
| --- | --- |
| Flux Kustomization | `clusters/dev/app.yaml` → `apps/overlays/dev/05-app` |
| BFF HelmRelease | `apps/app/base/helmrelease-nexus-bank-api.yaml` |
| BFF values | `apps/app/overlays/dev/values-nexus-bank-api.yaml` |
| Product Studio | `apps/app/base/produit-app-*.yaml` |
| Kong | `apps/kong/overlay/app-route.yaml`, `produit-app-route.yaml` |
| Reconcile | `.github/workflows/reconcile-app.yml` |

Product Studio uses the **same Keycloak client as web-app**: URL `https://iam.dev.sandbox.internal.nbank.fr/auth`, realm `internal`, client id `web-app`. Add `https://produit-app.dev.sandbox.internal.nbank.fr/*` to that client's redirect URIs if they are not already `*`.

`/api` on Product Studio proxies to `core-api-produit-api.api.svc.cluster.local`.
