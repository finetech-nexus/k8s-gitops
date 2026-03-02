# IAM dev overlay

Values for IAM (Keycloak + PostgreSQL) in the dev sandbox. The ConfigMap `iam-values` is generated from `values.yaml` by Kustomize.

## Keycloak TLS volume (`/tls`)

Keycloak is configured to use TLS cert/key from the Secret `keycloak-tls` at `/tls/tls.crt` and `/tls/tls.key` (see `KC_HTTPS_CERTIFICATE_FILE` / `KC_HTTPS_CERTIFICATE_KEY_FILE` in values).

- **Secret** `keycloak-tls`: created by cert-manager (or by Kustomize `secretGenerator` from `secrets/keycloak-tls.crt` and `secrets/keycloak-tls.key`).
- **Volume/mount**: `extraVolumes` and `extraVolumeMounts` in `values.yaml` must include the keycloak-tls volume and `/tls` mount. If they are commented out, Keycloak will fail with `NoSuchFileException /tls/tls.crt`.

### If `/tls` is missing in the pod

The repo values are correct; the cluster may be using an old ConfigMap or an old Helm release. Force Flux and Helm to apply the current values, then restart Keycloak:

```bash
# 1. Reconcile the Kustomization so the ConfigMap iam-values is updated
flux reconcile kustomization flux-system --with-source
# Or your IAM kustomization name, e.g.:
# flux reconcile kustomization iam -n flux-system

# 2. Reconcile the Helm release so it reads the new ConfigMap and upgrades the release
flux reconcile helmrelease iam -n iam

# 3. Restart the StatefulSet so new pods get the updated spec (with /tls volume)
kubectl rollout restart statefulset keycloak -n iam
kubectl rollout status statefulset keycloak -n iam

# 4. Verify the mount
kubectl exec -n iam keycloak-0 -c keycloak -- ls -la /tls
# Should show tls.crt and tls.key
```
