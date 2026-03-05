# Helm sources

Public Helm repos (Bitnami, Codecentric) need no auth. OCI repos at `ghcr.io/finetech-nexus/*` use the **ghcr-auth** secret so Flux can pull private charts.

## Create `ghcr-auth` (required for OCI charts)

The secret must exist in **flux-system** and use type `kubernetes.io/dockerconfigjson`. Use a GitHub PAT with **read:packages** (Classic) or **Packages: Read** (Fine-grained).

```bash
kubectl create secret docker-registry ghcr-auth -n flux-system \
  --docker-server=ghcr.io \
  --docker-username=YOUR_GITHUB_USERNAME \
  --docker-password=YOUR_GITHUB_PAT
```

Replace:
- **YOUR_GITHUB_USERNAME** — your GitHub login (e.g. `amiladi` or the org bot user).
- **YOUR_GITHUB_PAT** — a token with `read:packages` for `finetech-nexus` (or the repo/org where the packages live).

If the secret already exists, delete it first:

```bash
kubectl delete secret ghcr-auth -n flux-system --ignore-not-found
# then run the create command above
```

Then reconcile:

```bash
flux reconcile source helm core-banking-helm-chart-oci -n flux-system
flux reconcile kustomization api-core-banking-api -n flux-system
# or: ./scripts/validate.sh --reconcile
```
