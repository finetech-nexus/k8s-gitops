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

**Mechanism (k3s):** We use a **`*.server`** block (not `*.override`) so the zone `dev.sandbox.internal.nbank.fr` is handled first. The `.:53` block often runs the `kubernetes` plugin before custom overrides, which can return NXDOMAIN for unknown names. A dedicated server block for our zone runs rewrite then forwards to the cluster DNS (10.43.0.10). If your cluster DNS IP differs, edit the `forward .` line in `internal.server`. We use the `rewrite` plugin so that e.g. `iam.dev.sandbox.internal.nbank.fr` resolves to `keycloak.iam.svc.cluster.local` (with `answer auto` so the response keeps the original hostname).

**Apply:** The dev cluster applies this via `clusters/dev/coredns-custom.yaml`. After first apply (or after changing the ConfigMap), restart CoreDNS so it reloads:

```bash
kubectl rollout restart deployment -n kube-system coredns
# or, if CoreDNS runs as a DaemonSet:
kubectl rollout restart daemonset -n kube-system coredns
```

**Verify (host still unknown?):**

1. **ConfigMap present and applied**
   ```bash
   kubectl get configmap coredns-custom -n kube-system -o yaml
   ```
   If missing: apply the kustomization (e.g. `kubectl apply -k apps/coredns-custom` or `flux reconcile kustomization coredns-custom -n flux-system`).

2. **Restart CoreDNS** (required after any ConfigMap change)
   ```bash
   kubectl rollout restart deployment -n kube-system coredns
   # or: kubectl rollout restart daemonset -n kube-system coredns
   kubectl rollout status deployment/coredns -n kube-system
   ```

3. **k3s only:** `coredns-custom` is only loaded by **k3s**. If the cluster is vanilla Kubernetes or another distro, this ConfigMap is ignored; use another method (e.g. hostAliases or patch the main CoreDNS ConfigMap).

4. **Test resolution from a pod**
   ```bash
   kubectl run dns-test --rm -i --restart=Never --image=busybox:1.36 -- nslookup iam.dev.sandbox.internal.nbank.fr
   ```
   You should see an IP (the keycloak service). If it fails, CoreDNS is not applying the rewrite (wrong distro, not restarted, or ConfigMap not mounted).

5. **From the failing pod** (e.g. Keycloak): check which host it’s resolving and that it uses cluster DNS (no custom `/etc/resolv.conf` overriding nameservers).
   ```bash
   kubectl exec -n iam keycloak-0 -c keycloak -- cat /etc/resolv.conf
   kubectl exec -n iam keycloak-0 -c keycloak -- nslookup iam.dev.sandbox.internal.nbank.fr
   ```

Optional: run the script `./verify-in-cluster-dns.sh` from the repo root (with `kubectl` and cluster access).

**Add more hostnames:** Edit `configmap.yaml` and add a line inside the `internal.server` block (same format):

```
rewrite name <hostname> <service>.<namespace>.svc.cluster.local
```

Use the actual Service DNS name from `kubectl get svc -n <namespace>`. The `forward . 10.43.0.10` line must match your cluster DNS IP (see `Server:` in `nslookup` from any pod).
