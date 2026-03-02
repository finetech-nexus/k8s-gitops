# Kong (APIM)

Kong is used as **API Management (APIM)**, not as a Kubernetes Ingress controller. Routes are defined in Kong’s declarative config, not as Kubernetes `Ingress` resources.

## Core-banking webapp

The webapp is **already exposed via NGINX Ingress** (see `apps/core-banking/overlays/dev/values-core-banking.yaml`: `webapp.ingress` — hostname `web-app.dev.sandbox.nbank.fr`, path `/`, nginx + cert-manager annotations). NGINX Ingress targets the `webapp` Service in the `core-banking` namespace. No Kong config is required for that.

**Optional:** To expose the webapp through Kong as well (or instead of NGINX), use the declarative config:

- **File:** `kong-declarative-webapp.yaml`
- **Route host:** `web-app.dev.sandbox.nbank.fr` (same as `webapp.ingress.hostname` in values)
- **Upstream:** ingress host URL `web-app.dev.sandbox.nbank.fr:80` (no cluster-internal `.svc.cluster.local`); Kong proxies to the NGINX Ingress URL. Kong must be able to resolve and reach that host.

If you use Kong for this host, consider disabling the chart Ingress (`webapp.ingress.enabled: false`) to avoid two entry points for the same host.

### Browser: `net::ERR_NAME_NOT_RESOLVED`

The hostname (e.g. `web-app.dev.sandbox.nbank.fr`) must resolve in DNS. If you don’t have a real DNS record yet:

1. **Get the ingress/load balancer IP** (NGINX Ingress or Kong, depending on what serves the host):
   ```bash
   kubectl get svc -n ingress-nginx   # or your NGINX Ingress namespace
   # or
   kubectl get svc -n apim            # if Kong proxy is the entry
   ```
   Use the `EXTERNAL-IP` (or `LoadBalancer` hostname) of the ingress/proxy service.

2. **Add a local hosts entry** on your machine (so the browser can resolve the name):
   ```bash
   # macOS/Linux: edit /etc/hosts (needs sudo)
   <EXTERNAL-IP>   web-app.dev.sandbox.nbank.fr
   ```

3. Reload the browser and open `https://web-app.dev.sandbox.nbank.fr` (or `http://` if TLS isn’t set up). For HTTPS with a custom host, the certificate may show a warning unless you use a public DNS name and a proper issuer (e.g. cert-manager).

Alternatively, create a real DNS record (A or CNAME) for `web-app.dev.sandbox.nbank.fr` pointing at that same IP.

### Loading the config into Kong

1. **DB-less + declarative config (recommended)**  
   Run Kong in DB-less mode and load this file as the declarative config (e.g. via Helm values that mount a ConfigMap built from `kong-declarative-webapp.yaml`, or `KONG_DECLARATIVE_CONFIG`). Merge or append this snippet into your main Kong declarative config if you already have one.

2. **Admin API**  
   If Kong uses a DB, you can create the Service and Route via the Kong Admin API (or with [decK](https://docs.konghq.com/deck/)).

3. **TLS**  
   TLS for `web-app.dev.sandbox.nbank.fr` is configured on Kong’s proxy listener or on the load balancer in front of Kong, not in this declarative file. Use cert-manager or your existing TLS flow and attach the certificate to Kong’s HTTPS listener.

### Adjusting the upstream

If your webapp Service has a different name or namespace, edit `kong-declarative-webapp.yaml`: set `services[].host` to the Kubernetes Service DNS name (e.g. `my-webapp.my-namespace.svc.cluster.local`).

## Existing Ingress resources

`ingress-core-banking.yaml` and `ingress-routes.yaml` are present for compatibility with a Kong Ingress Controller setup. If Kong is deployed **only** as APIM (no Ingress controller), those Ingress resources are not used; rely on declarative config (e.g. `kong-declarative-webapp.yaml`) instead.
