# k8s-gitops

Flux GitOps repo for Nexus Bank Kubernetes clusters.

## Required secrets (create once per cluster)

### cert-manager — Cloudflare API token (DNS-01)

For ACME DNS-01 challenges (ClusterIssuers in `apps/cert-manager/`). Create in the **cert-manager** namespace:

```bash
kubectl create secret generic cloudflare-api-token -n cert-manager \
  --from-literal=api-token=YOUR_CLOUDFLARE_API_TOKEN
```

To update the token (e.g. after rotation):

```bash
kubectl create secret generic cloudflare-api-token -n cert-manager \
  --from-literal=api-token=YOUR_NEW_TOKEN \
  --dry-run=client -o yaml | kubectl apply -f -
```

Use a Cloudflare API token with **Zone:DNS:Edit** for the relevant zone(s). See `apps/cert-manager/cluster-issuers.yaml` for details.

### Flux — GHCR (OCI Helm charts)

For pulling Helm charts from `ghcr.io/finetech-nexus/*`. See **apps/sources/README.md**.

## Scripts

- **scripts/validate.sh** — Kustomize build + optional Flux reconcile. See script help for `--reconcile`, `--prune`, `--delete`.
