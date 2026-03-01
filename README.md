# k8s-gitops

```bash
export GITHUB_TOKEN=your_github_pat   # repo scope

flux bootstrap git \
  --url=https://github.com/finetech-nexus/k8s-gitops.git \
  --branch=main \
  --path=clusters/dev \
  --token-auth \
  --password="$GITHUB_TOKEN"
```
flux get kustomizations -n flux-system

flux reconcile source git flux-system -n flux-system

flux reconcile kustomization flux-system -n flux-system
flux reconcile kustomization cert-manager -n flux-system
flux reconcile kustomization cert-manager-issuers -n flux-system
flux reconcile kustomization platform -n flux-system
flux reconcile kustomization kong -n flux-system
flux reconcile kustomization kong-ingress -n flux-system
flux reconcile kustomization monitoring -n flux-system
flux reconcile kustomization core-banking -n flux-system
flux reconcile kustomization apis -n flux-system
flux reconcile kustomization identity -n flux-system

flux get helmreleases -n core-banking

for log kubectl logs -n flux-system deploy kustomize-controller -f

#for debug
kubectl get kustomizations -n flux-system -w

flux get helmreleases -n core-banking


kubectl create secret docker-registry ghcr-auth \
  --namespace flux-system \
  --docker-server=ghcr.io \
  --docker-username=ammiladi \            
  --docker-password=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

  

export KUBECONFIG=/path/to/your/kubeconfig 

Flux GitOps repo for Nexus Bank (dev cluster: Kong + optional platform/core/apis).

## Bootstrap (private repo)


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
# Pull repo and reconcile the whole dev stack (root applies clusters/dev)
flux reconcile source git flux-system -n flux-system
flux reconcile kustomization flux-system -n flux-system
```

To force-reconcile every kustomization by name:

```bash
flux reconcile source git flux-system -n flux-system
for k in flux-system cert-manager cert-manager-issuers platform kong kong-ingress monitoring core-banking apis identity; do
  flux reconcile kustomization $k -n flux-system
done
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

## TLS management

Certificates are issued by **cert-manager** using Let’s Encrypt (ACME). In dev, the cert-manager Kustomization is **suspended** by default; enable it when you need TLS.

### ClusterIssuers (`apps/cert-manager/cluster-issuers.yaml`)

| Issuer        | Use case          | HTTP-01 ingress class |
|---------------|-------------------|------------------------|
| **nbank**     | Production (nginx) | nginx                |
| **nbank-staging** | Staging (nginx) | nginx                |
| **nbank-dev**     | Dev (Let's Encrypt staging) | nginx        |

- **App charts that use nginx Ingress** (e.g. fineract-hook, core-banking chart ingress): use `cert-manager.io/cluster-issuer: nbank` (prod), `nbank-staging` (staging), or **nbank-dev** (dev; uses Let's Encrypt staging to avoid prod rate limits).
- **Kong-routed Ingresses**: TLS is not managed by cert-manager (issuers use nginx class). Use LB-level certs or terminate TLS elsewhere if needed.

### Enabling TLS in dev

1. **Enable cert-manager:** In `clusters/dev/cert-manager.yaml` set `suspend: false`, push, then:
   ```bash
   flux reconcile kustomization cert-manager -n flux-system
   ```
2. **Apply ClusterIssuers:** The **cert-manager-issuers** Kustomization (`clusters/dev/cert-manager-issuers.yaml`) applies `./apps/cert-manager` and depends on cert-manager install. Once cert-manager is enabled, ClusterIssuers are applied automatically.
3. **DNS:** Ensure each host (e.g. `core-banking.dev.sandbox.nbank.fr`) resolves to the Kong LoadBalancer (or the ingress that will serve the ACME challenge). Let’s Encrypt will hit `http://<host>/.well-known/acme-challenge/...`.

### Summary

- **cert-manager** install: `clusters/dev/cert-manager.yaml` → path `./apps/cert-manager-install`.
- **ClusterIssuers**: `apps/cert-manager/cluster-issuers.yaml` (nbank, nbank-staging, nbank-dev). Applied via cert-manager-issuers Kustomization.
- ACME contact email is set to `certs@nbank.fr` in the ClusterIssuers (domain: nbank.fr). Change in `apps/cert-manager/cluster-issuers.yaml` if needed.

---

## Core-banking: why is no pod created?

Run these to see where it stops:

```bash
# 1. Is the core-banking Kustomization applied?
flux get kustomization core-banking -n flux-system

# 2. Are HelmReleases present and ready?
flux get helmreleases -n core-banking

# 3. If a HelmRelease is not Ready, inspect it
kubectl describe helmrelease core-banking -n core-banking
kubectl describe helmrelease fineract-hook -n core-banking

# 4. Helm controller logs (chart pull / install errors)
kubectl logs -n flux-system deploy/helm-controller -f --tail=100

# 5. Pods in namespace
kubectl get pods -n core-banking
kubectl get all -n core-banking
```

**Common causes:**

| Cause | What to check / fix |
|-------|----------------------|
| **core-banking Kustomization not Ready** | It depends on **sources**. Run `flux get kustomization sources -n flux-system` and fix sources (e.g. duplicate HelmRepository) so it’s Ready; then reconcile core-banking. |
| **HelmRelease not Ready** | `kubectl describe helmrelease core-banking -n core-banking` → look at **Status.Conditions** and **Message**. |
| **OCI chart pull failed** | Create the `ghcr-auth` secret in flux-system (see GHCR auth above). Reconcile HelmRepository: `flux reconcile source helm core-banking-helm-chart-oci -n flux-system`. |
| **Chart version missing** | HelmRelease uses `fin-engine` version `1.4.1-SNAPSHOT` from `core-banking-helm-chart-oci`. Ensure that version exists in the OCI repo. |
| **Pods stuck Init / ImagePullBackOff** | Values reference image `docker.io/nexusbank/fineract-custom:1.13.1` and DB host `fineract-mysql`. Check image pull and that MySQL (fineract-mysql) is running if the chart expects it. |

---

## Structure

- **clusters/dev** — Flux sync path; Kong active; platform, cert-manager, core, apis, identity, monitoring, kong-ingress suspended.
- **apps/kong/** — HelmRelease, namespace, Ingress routes (apim-routes, core-banking).
- **apps/** — sources (HelmRepositories), kong-ingress, monitoring, overlays (api, core-banking, etc.).
