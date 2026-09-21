# App layer — BFF (`nexus-bank-api`)

Flux deploys the mobile/web BFF into namespace `app` from Helm chart `nexus-bank-app` (`ghcr.io/finetech-nexus/nexus-bank-api-chart`).

Product Studio is a subchart of **core-api-charts** (`produit-app`), deployed with the `apis` layer, not here.

| Item | Path |
| --- | --- |
| Flux Kustomization | `clusters/dev/app.yaml` → `apps/overlays/dev/05-app` |
| BFF HelmRelease | `apps/app/base/helmrelease-nexus-bank-api.yaml` |
| BFF values | `apps/app/overlays/dev/values-nexus-bank-api.yaml` |
| Kong | `apps/kong/overlay/app-route.yaml` |
| Reconcile | `.github/workflows/reconcile-app.yml` |
