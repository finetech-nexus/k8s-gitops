# Kong APIM

Kong API Gateway. TLS via cert-manager (nbank-dev). Routes in `overlay/` are applied by Flux Kustomization `kong-routes` (depends on `kong` install).

## Quick reference: hostname → backend

| External hostname | Route / action | Backend (internal Host / service) |
|-------------------|----------------|------------------------------------|
| apim.nbank.fr | app-api-route (proxy) | app.api.dev.sandbox.internal.nbank.fr |
| app.api.dev.sandbox.nbank.fr | app-api-route (proxy) | app.api.dev.sandbox.internal.nbank.fr |
| web-app.dev.sandbox.nbank.fr | webapp-route | web-app.dev.sandbox.internal.nbank.fr |
| fynams.dev.sandbox.nbank.fr | fynams-route | fynams.dev.sandbox.internal.nbank.fr |
| backoffice.kyc.dev.sandbox.nbank.fr | backoffice-kyc-route | backoffice.kyc.dev.sandbox.internal.nbank.fr |
| workflowdashboard.kyc.dev.sandbox.nbank.fr | workflowdashboard-kyc-route | workflowdashboard.kyc.dev.sandbox.internal.nbank.fr |
| workflowsvc.kyc.dev.sandbox.nbank.fr | workflowsvc-kyc-route | workflowsvc.kyc.dev.sandbox.internal.nbank.fr |
| iam.dev.sandbox.nbank.fr | iam-route | iam.dev.sandbox.internal.nbank.fr |
| docs.nbank.fr | docs-route | docs.nbank.fr (ingress-nginx → docs service) |
| reconciliation-api.api.dev.sandbox.nbank.fr | reconciliation-api-route | reconciliation-api.api.dev.sandbox.internal.nbank.fr |
| reconciliation-app.dev.sandbox.nbank.fr | reconciliation-app-route | reconciliation-app.dev.sandbox.internal.nbank.fr |
| aml-app.dev.sandbox.nbank.fr | aml-app-route | aml-app.dev.sandbox.internal.nbank.fr |
| aml-auth.dev.sandbox.nbank.fr | aml-auth-route | aml-auth.dev.sandbox.internal.nbank.fr |
| aml-api.api.dev.sandbox.nbank.fr | aml-api-route | aml-api.api.dev.sandbox.internal.nbank.fr |

## KongPlugins

Plugins are defined in **overlay/kong-plugins.yaml** (applied first by the overlay):

- **internal-only** — ip-restriction (allow all); used by webapp, fynams, kyc (backoffice, workflowdashboard, workflowsvc), iam, app-api routes.

**apim.nbank.fr:** Same route as app API (`app-api-route`). For https://apim.nbank.fr/api-docs to work, **DNS for apim.nbank.fr must point to Kong's LoadBalancer IP** (not ingress-nginx). Then Kong receives the request and proxies to ingress-nginx with Host `app.api.dev.sandbox.internal.nbank.fr`. If apim.nbank.fr points to ingress-nginx you get 404 because nginx has no Ingress for that host.

### If `kubectl get kongplugin -A` shows no resources

1. Check that Kong CRDs exist (Kong install must have run):  
   `kubectl get crd | grep kong`

2. Reconcile the overlay so it (re)applies KongPlugins and routes:  
   `flux reconcile kustomization kong-routes -n flux-system`

3. Or apply the overlay manually from the repo root:  
   `kustomize build apps/kong/overlay | kubectl apply -f -`

4. Confirm plugins in **apim** namespace:  
   `kubectl get kongplugin -n apim`
