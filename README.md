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

### cert-manager — Internal CA (ClusterIssuer internal-ca)

For the **internal-ca** ClusterIssuer, create a secret with your CA certificate and key (e.g. `certificate.crt` and `_.nbank.fr_private_key.key` in the project root):

```bash
kubectl create secret tls internal-ca-keypair -n cert-manager \
  --cert=certificate.crt \
  --key=_.nbank.fr_private_key.key
```

Run from the directory that contains the cert and key, or use full paths.

### Flux — GHCR (OCI Helm charts)

For pulling Helm charts from `ghcr.io/finetech-nexus/*`. See **apps/sources/README.md**.

## Scripts

- **scripts/validate.sh** — Kustomize build + optional Flux reconcile. See script help for `--reconcile`, `--prune`, `--delete`.
