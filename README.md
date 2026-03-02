# k8s-gitops

Flux GitOps repository for the Nexus Bank Kubernetes clusters. Defines cluster configs, app kustomizations, and Helm releases.

## Structure

- **`clusters/<env>/`** — Per-environment Flux kustomizations (dev, staging, production). Each env has:
  - `kustomization.yaml` — lists which Flux Kustomization/HelmRelease resources to apply
  - `flux-system.yaml` / `sources.yaml` — Git source and optional Helm repositories
  - `cert-manager.yaml`, `kong.yaml`, `core-banking.yaml`, etc. — Flux Kustomizations that point at paths under `./apps` or `./apps/overlays/<env>/...`
- **`apps/`** — Base app definitions and shared sources:
  - `sources/` — Helm repositories (OCIR, etc.)
  - `kong/`, `kong-ingress/`, `monitoring/`, `cert-manager/`, etc. — Kustomize/Helm for each area
  - `core-banking/`, `payment-hub/`, etc. — App charts and overlays
- **`apps/overlays/<env>/`** — Environment overlays (e.g. `01-platform`, `02-identity`, `03-core`, `04-apis`) that reference the app charts with env-specific values.

## CI/CD

GitHub Actions (`.github/workflows/validate.yml`) runs on push to `main` and on pull requests that touch `apps/`, `clusters/`, or `docs/`. It runs `kustomize build` on the cluster config and on every app path that Flux uses (sources, cert-manager, kong, overlays for dev/staging/production), so broken YAML or invalid refs fail the check before merge.

## Apply

Apply the cluster config for an env (e.g. dev) with:

```bash
kubectl apply -k clusters/dev
```

(Assumes Flux is installed and `kubectl` is pointed at the target cluster.)

## Flux: reconcile

After pushing changes, reconcile so Flux picks them up:

1. Reconcile the Git source (so Flux fetches latest commit):
   ```bash
   flux reconcile source git flux-system -n flux-system
   ```

2. Reconcile the root kustomization (which then triggers dependencies):
   ```bash
   flux reconcile kustomization flux-system -n flux-system
   ```

3. Optionally reconcile a specific kustomization (e.g. core-banking, Kong):
   ```bash
   flux reconcile kustomization core-banking -n flux-system
   flux reconcile kustomization kong -n flux-system
   ```

To run all kustomizations in a loop (e.g. after fixing a broken source):

```bash
flux reconcile source git flux-system -n flux-system
flux reconcile kustomization flux-system -n flux-system
for name in $(flux get kustomizations -n flux-system --no-header 2>/dev/null | awk '{print $1}'); do
  flux reconcile kustomization "$name" -n flux-system --timeout=5m
done
```

Use `--timeout=5m` (or `--timeout=0`) if you hit "context deadline exceeded".

## Troubleshooting

- **Sources / kustomize build failing**  
  Run `flux get kustomizations -n flux-system` and `flux get sources -n flux-system`. For a failing kustomization, run `kubectl describe kustomization <name> -n flux-system` and check the kustomize-controller logs. Fix any duplicate resources or invalid YAML in `apps/sources/` (e.g. duplicate HelmRepository entries).

- **cert-manager not ready**  
  Ensure the kustomization for cert-manager is not suspended: in `clusters/<env>/cert-manager.yaml` set `suspend: false`, then reconcile.

- **Core-banking pod not created / HelmRelease not ready**  
  Check: `flux get kustomization core-banking -n flux-system`, `flux get helmrelease -n <core-banking-namespace>`, and `kubectl describe helmrelease ...`. Check helm-controller logs. Common causes: sources not ready, OCI/auth or chart version issues, or image/DB init failures (e.g. wrong MariaDB image or `mysql.primary.image` in values).

- **MariaDB / image pull**  
  If the chart uses a legacy or missing image (e.g. `bitnamilegacy/mariadb`), override in the overlay values with a valid image (e.g. `bitnami/mariadb:11.4.7-2`) and set `mysql.primary.image` (and `mysql.image` if needed) so the subchart uses it. Then reconcile and optionally scale the StatefulSet to refresh the pod.

## Docs

- **Fineract OAuth2 + Keycloak** — See `docs/fineract-oauth2-keycloak.md` (if present) for configuring Fineract with Keycloak and multi-realm issuer list (`FINERACT_SECURITY_OAUTH_ALLOWED_ISSUERS`).

## References

- [Flux](https://fluxcd.io/) — GitOps for Kubernetes
- Cluster bootstrap: apply `clusters/<env>` with Flux already installed and kubeconfig set to the target cluster
