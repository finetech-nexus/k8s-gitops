# k8s-gitops

flux reconcile source git flux-system -n flux-system
flux reconcile kustomization core-banking -n flux-system
flux get helmreleases -n core-banking

for log kubectl logs -n flux-system deploy/kustomize-controller -f

export KUBECONFIG=/path/to/your/kubeconfig 

Flux GitOps repo for Nexus Bank (dev cluster: Kong + optional platform/core/apis).

## Bootstrap (private repo)

```bash
export GITHUB_TOKEN=your_github_pat   # repo scope

flux bootstrap git \
  --url=https://github.com/finetech-nexus/k8s-gitops.git \
  --branch=main \
  --path=clusters/dev \
  --token-auth \
  --password="$GITHUB_TOKEN"
```

This creates the `flux-system` secret and GitRepository; no extra steps.

## If Flux is already installed (switch to this repo or fix auth)

Create the Git credential secret, then reconcile:

```bash
kubectl create secret generic flux-system -n flux-system \
  --from-literal=username=git \
  --from-literal=password=YOUR_GITHUB_PAT

kubectl annotate gitrepository flux-system -n flux-system \
  reconcile.fluxcd.io/requestedAt="$(date +%s)" --overwrite
```

The `GitRepository` in `clusters/dev/flux-system/gotk-sync.yaml` is configured with `secretRef.name: flux-system` for private clone.

## GHCR auth (OCI Helm charts)

The OCI HelmRepositories (`core-banking-helm-chart-oci`, `core-banking-api-chart-oci`) use `secretRef.name: ghcr-auth`. Create the secret once:

```bash
kubectl create secret docker-registry ghcr-auth \
  --namespace flux-system \
  --docker-server=ghcr.io \
  --docker-username=YOUR_GITHUB_USERNAME \
  --docker-password=YOUR_GITHUB_PAT
```

Then reconcile sources so the HelmRepositories can pull:

```bash
flux reconcile source helm core-banking-helm-chart-oci -n flux-system
flux reconcile source helm core-banking-api-chart-oci -n flux-system
```

## After push

```bash
flux reconcile source git flux-system -n flux-system
flux reconcile kustomization flux-system -n flux-system
flux reconcile kustomization kong -n flux-system
```

## APIM (Kong) — routing

Kong is the API gateway. Routing is defined with **Kubernetes Ingress** resources that use `ingressClassName: kong`. Kong watches these and programs routes.

### Current routes (`apps/kong/`)

| Host | Backend service | Namespace |
|------|-----------------|-----------|
| `*.dev.sandbox.nbank.fr` | `public-app:80` | apim |
| `*.internal.dev.sandbox.nbank.fr` | `internal-app:80` | apim |
| `core-banking.dev.sandbox.nbank.fr` | `core-banking:80` | core-banking |

Backend services (`public-app`, `internal-app`, `core-banking`) must exist and be reachable; add them via your app HelmReleases or Deployments.

### Add a new route

1. Create an Ingress in the **same namespace as the backend service** (or in `apim` if the backend is there):

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: my-api
  namespace: apim
  annotations:
    konghq.com/strip-path: "false"
spec:
  ingressClassName: kong
  rules:
    - host: "api.dev.sandbox.nbank.fr"
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: my-backend
                port:
                  number: 80
```

2. Add the file under `apps/kong/` and list it in `apps/kong/kustomization.yaml`.
3. Push; Flux applies it and Kong picks up the route.

### Cross-namespace routing

Ingress only allows backends in the **same namespace** as the Ingress. To route to a service in another namespace you can:

- Put the Ingress in that namespace (e.g. `ingress-core-banking.yaml` in `core-banking`), or
- Expose the backend in `apim` via a Service that points to the other namespace (e.g. ExternalName or a duplicate Service with the same selector semantics if the pods are in another ns).

### DNS

Point your domains to the **Kong LoadBalancer IP**:

```bash
kubectl get svc -n apim -l app.kubernetes.io/component=proxy
```

Create A (or CNAME) records for `*.dev.sandbox.nbank.fr`, `*.internal.dev.sandbox.nbank.fr`, `core-banking.dev.sandbox.nbank.fr` to that IP.

### Optional: Kong annotations

- `konghq.com/strip-path: "true"` — strip the path prefix before forwarding.
- `konghq.com/plugins: rate-limiting, key-auth` — attach Kong plugins (create Plugin CRs or use annotations per doc).
- [Kong Ingress Controller annotations](https://docs.konghq.com/kubernetes-ingress-controller/latest/reference/annotations/)

---

## Structure

- **clusters/dev** — Flux sync path; Kong active; platform, cert-manager, core, apis, identity, monitoring, kong-ingress suspended.
- **apps/kong/** — HelmRelease, namespace, Ingress routes (apim-routes, core-banking).
- **apps/** — sources (HelmRepositories), kong-ingress, monitoring, overlays (api, core-banking, etc.).
