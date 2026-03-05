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

**Private repo:** The manifest references `secretRef.name: flux-system`. If that Secret was deleted, re-create it before or after applying.

Your repo URL is **HTTPS** (`https://github.com/...`), so the secret must use HTTPS auth (username + token), not SSH:

```bash
# Delete wrong/missing secret if it exists
kubectl delete secret flux-system -n flux-system --ignore-not-found

# HTTPS: GitHub token (recommended when using https:// URL)
kubectl create secret generic flux-system -n flux-system \
  --from-literal=username=git \
  --from-literal=password=YOUR_GITHUB_PERSONAL_ACCESS_TOKEN
```

If you use **SSH** instead, the GitRepository URL must be `git@github.com:finetech-nexus/k8s-gitops.git` and the secret must include the private key:

```bash
kubectl delete secret flux-system -n flux-system --ignore-not-found
kubectl create secret generic flux-system -n flux-system \
  --from-literal=identity="$(cat ~/.ssh/your_deploy_key)" \
  --from-literal=identity.pub="$(cat ~/.ssh/your_deploy_key.pub)" \
  --type=kubernetes.io/ssh-auth
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

## Troubleshooting

**Error: `invalid 'ssh' auth option: 'identity' is required`**

The GitRepository uses an **HTTPS** URL but the `flux-system` secret is in SSH format (or incomplete). Use an HTTPS secret:

```bash
kubectl delete secret flux-system -n flux-system --ignore-not-found
kubectl create secret generic flux-system -n flux-system \
  --from-literal=username=git \
  --from-literal=password=YOUR_GITHUB_TOKEN
```

Then: `flux reconcile source git flux-system -n flux-system`
