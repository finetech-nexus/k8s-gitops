# CoreDNS custom (k3s)

Adds in-cluster DNS so `*.dev.sandbox.internal.nbank.fr` hostnames resolve to the corresponding Kubernetes services. Used so pods (e.g. Keycloak, core-banking) can call each other by Ingress hostname without `UnknownHostException`.

**Mechanism:** k3s merges the ConfigMap `coredns-custom` in `kube-system`: keys matching `*.override` are imported into the CoreDNS `.:53` block. We use the `rewrite` plugin so that e.g. `iam.dev.sandbox.internal.nbank.fr` resolves to `keycloak.iam.svc.cluster.local` (with `answer auto` so the response keeps the original hostname).

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
