# Re-create Flux GitRepository and Kustomization after --delete

If you ran `./scripts/validate.sh --delete` (or removed the Flux sources manually), the **GitRepository** and **Kustomization** `flux-system` are gone. Re-create them from your local clone.

## Option 1: Apply the sync file (simplest)

From the **k8s-gitops** repo root:

```bash
kubectl apply -f clusters/dev/flux-system/gotk-sync.yaml
```

This re-creates:

- **GitRepository** `flux-system` (url: https://github.com/finetech-nexus/k8s-gitops.git, branch: main)
- **Kustomization** `flux-system` (path: ./clusters/dev, prune: true)

**Private repo:** The manifest references `secretRef.name: flux-system`. If that Secret was deleted, re-create it before or after applying, for example:

```bash
# Deploy key (e.g. from flux bootstrap). Replace with your key.
kubectl create secret generic flux-system -n flux-system \
  --from-literal=identity="$(cat ~/.ssh/flux_id_rsa)" \
  --from-literal=identity.pub="$(cat ~/.ssh/flux_id_rsa.pub)" \
  --type=kubernetes.io/ssh-auth
```

Or use HTTPS with a token:

```bash
kubectl create secret generic flux-system -n flux-system \
  --from-literal=username=git \
  --from-literal=password=YOUR_GITHUB_TOKEN
```

Then run:

```bash
./scripts/validate.sh --reconcile
```

## Option 2: flux create (no local file)

**Public repo (no secret):**

```bash
flux create source git flux-system \
  --url=https://github.com/finetech-nexus/k8s-gitops.git \
  --branch=main \
  --interval=1m \
  --namespace=flux-system

flux create kustomization flux-system \
  --source=flux-system \
  --path=./clusters/dev \
  --prune=true \
  --interval=10m \
  --namespace=flux-system
```

**Private repo:** Create the secret first (as above), then add `--secret-ref=flux-system` to the `flux create source git` command.

## Verify

```bash
kubectl get gitrepository,kustomization -n flux-system
flux reconcile source git flux-system -n flux-system
flux reconcile kustomization flux-system -n flux-system
```
