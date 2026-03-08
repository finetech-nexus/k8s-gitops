# Kong APIM

Kong API Gateway. TLS via cert-manager (nbank-dev). Routes in `overlay/` are applied by Flux Kustomization `kong-routes` (depends on `kong` install).

## Quick reference: hostname → backend

| External hostname | Route / action | Backend (internal Host / service) |
|-------------------|----------------|------------------------------------|
| apim.nbank.fr | 301 redirect | → https://app.api.dev.sandbox.nbank.fr |
| app.api.dev.sandbox.nbank.fr | app-api-route | app.api.dev.sandbox.internal.nbank.fr |
| app-ws.api.dev.sandbox.nbank.fr | app-ws-route | app-ws.api.dev.sandbox.internal.nbank.fr |
| web-app.dev.sandbox.nbank.fr | webapp-route | web-app.dev.sandbox.internal.nbank.fr |
| iam.dev.sandbox.nbank.fr | iam-route | iam.dev.sandbox.internal.nbank.fr |

## KongPlugins

Plugins are defined in **overlay/kong-plugins.yaml** (applied first by the overlay):

- **internal-only** — ip-restriction (allow all); used by webapp, iam, app-api, app-ws routes.
- **apim-redirect-to-app-api** — redirect 301 to app.api.dev.sandbox.nbank.fr; used by apim-redirect-route.

### If `kubectl get kongplugin -A` shows no resources

1. Check that Kong CRDs exist (Kong install must have run):  
   `kubectl get crd | grep kong`

2. Reconcile the overlay so it (re)applies KongPlugins and routes:  
   `flux reconcile kustomization kong-routes -n flux-system`

3. Or apply the overlay manually from the repo root:  
   `kustomize build apps/kong/overlay | kubectl apply -f -`

4. Confirm plugins in **apim** namespace:  
   `kubectl get kongplugin -n apim`
