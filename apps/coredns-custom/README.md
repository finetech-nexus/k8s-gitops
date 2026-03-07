# CoreDNS custom (k3s)

Adds in-cluster DNS so `*.dev.sandbox.internal.nbank.fr` hostnames resolve to the corresponding Kubernetes services. Used so pods (e.g. Keycloak, core-banking) can call each other by Ingress hostname without `UnknownHostException`.

## How CoreDNS fits in

- **Cluster DNS:** Every pod uses the cluster DNS (CoreDNS) for name resolution. By default it only knows `*.svc.cluster.local` (Kubernetes Services) and forwards the rest to upstream DNS.
- **Our config:** We add **rewrite** rules so that when a pod looks up e.g. `iam.dev.sandbox.internal.nbank.fr`, CoreDNS answers with the IP of `keycloak.iam.svc.cluster.local` (and with `answer auto` the response still says the original hostname, so TLS/redirects work).
- **Where URLs are defined:** The hostnames/URLs themselves are **not** defined in CoreDNS. They are set in each app’s config:
  - **IAM:** `apps/iam/overlays/dev/values.yaml` — `KEYCLOAK_FRONTEND_URL`, `KC_HOSTNAME`, Ingress `host` / `tls.hosts`
  - **Core-banking:** `apps/core-banking/overlays/dev/values-core-banking.yaml` — hostnames, OAuth URLs, Ingress hosts
  - **API (core-banking-api, nexus-bank-api):** `apps/api/overlays/dev/values-core-banking-api.yaml`, `apps/app/overlays/dev/values-nexus-bank-api.yaml` — `KEYCLOAK_URL`, Ingress hosts
  - **KYC:** `apps/kyc/overlays/dev/values.yaml` — hosts, `KEYCLOAK_URL`, CORS, etc.
  - **Kong:** `apps/kong/overlay/nginx-ingress-upstream.yaml` — `konghq.com/host-header` for each service
- **Role of this ConfigMap:** It only tells CoreDNS “when someone asks for this hostname, resolve to this service.” So the same URL that appears in env vars and Ingress also resolves inside the cluster.

**Mechanism (k3s):** k3s merges the ConfigMap `coredns-custom` in `kube-system`: keys matching `*.override` are imported into the CoreDNS `.:53` block. We use the `rewrite` plugin so that e.g. `iam.dev.sandbox.internal.nbank.fr` resolves to `keycloak.iam.svc.cluster.local` (with `answer auto` so the response keeps the original hostname).

**Apply:** The dev cluster applies this via `clusters/dev/coredns-custom.yaml`. After first apply (or after changing the ConfigMap), restart CoreDNS so it reloads:

```bash
kubectl rollout restart deployment -n kube-system coredns
# or, if CoreDNS runs as a DaemonSet:
kubectl rollout restart daemonset -n kube-system coredns
```

**Add more hostnames:** Edit `configmap.yaml` and add lines to `internal-hosts.override`:

```
rewrite name exact <hostname> <service>.<namespace>.svc.cluster.local answer auto
```

Use the actual Service DNS name for the app (e.g. from `kubectl get svc -n <namespace>`).
