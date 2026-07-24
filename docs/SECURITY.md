# Security model

Fetching caller-controlled URLs is the main trust boundary. The default configuration is intended for public-web analysis, not private-network monitoring.

## URL and network controls

Before every request, including redirects, the fetcher:

- accepts only HTTP and HTTPS;
- rejects embedded usernames/passwords;
- allows only configured ports (`80,443` by default);
- resolves the hostname and rejects the target if any answer is non-global;
- rejects direct private, loopback, link-local, multicast, unspecified and reserved IP literals;
- connects to one validated IP while retaining the public hostname for the HTTP Host header and TLS SNI;
- ignores `HTTP_PROXY`, `HTTPS_PROXY` and related environment variables;
- applies time, redirect, connection, concurrency and decompressed-body limits.

Checking every DNS answer is intentionally conservative: a hostname with mixed public/private answers is rejected. Pinning the selected answer for the connection reduces time-of-check/time-of-use DNS-rebinding exposure.

`SEO_ALLOW_PRIVATE_HOSTS=true` disables the central address boundary and should only be used in a trusted, isolated deployment with an explicit egress policy. Never enable it on a public multi-tenant endpoint.

## Crawl controls

- Site audits stay on the requested host unless subdomains are explicitly included.
- Query parameters are excluded by default and tracking parameters are removed.
- Page/depth/concurrency budgets are enforced by both request validation and server settings.
- `robots.txt` is respected by default. Network and 5xx errors are handled conservatively in line with [RFC 9309](https://www.rfc-editor.org/rfc/rfc9309.html).
- XML is parsed with `defusedxml`; sitemap documents, nesting, URL inventory, output samples and gzip decompression are bounded.
- HTML/JSON-LD evidence arrays are capped before returning them.

Robots compliance is a crawler policy, not an access-control mechanism. Site owners should protect sensitive content with authentication.

## API boundary

Set `SEO_API_KEY` for direct exposure and compare it through the `X-API-Key` header. The comparison is constant-time. In production, also use an authenticated reverse proxy or API gateway for per-client keys, rate limits, TLS, request-body limits and abuse controls.

The built-in key is a single shared secret, not a tenant/authorization system. `/healthz`, `/readyz`, `/metrics`, API docs and the root route remain operational endpoints. Restrict them at the proxy if your environment requires it.

CORS is absent unless `SEO_CORS_ORIGINS` contains explicit origins. It is not an authentication mechanism.

Analysis responses add a request ID, `nosniff`, a no-referrer policy and `Cache-Control: no-store`. Metrics label only route templates, methods and statuses—not analyzed URLs or secrets. Application logs likewise record route metadata rather than URL query values.

## External services and data handling

PageSpeed is disabled by default. When enabled and requested, the final validated public URL is sent to Google PageSpeed Insights. That creates a third-party data and quota dependency; document it in your privacy/processing model and protect `SEO_PAGESPEED_API_KEY` in the environment.

Page HTML is processed in memory and cached in summarized analysis form for a bounded TTL. This project has no database and does not intentionally persist fetched HTML. Multi-worker deployments have independent caches and metrics.

## Container posture

The supplied image runs as a non-root system user. Compose binds to loopback, drops all Linux capabilities, sets `no-new-privileges`, uses a read-only root filesystem, provides a small `/tmp` tmpfs and declares a memory limit. Put a production reverse proxy in front; do not expose the Uvicorn development topology as a complete security perimeter.

Container restrictions do not replace outbound firewall rules. For higher-risk deployments, allow egress only to public HTTP(S), run in a dedicated network/namespace, configure DNS deliberately and set infrastructure-level CPU/request/time limits.

## Residual risks

- Large or adversarial HTML can still consume parser CPU within the configured byte limit.
- Application-level rate limiting is intentionally delegated to a gateway.
- A single process-local cache is not a distributed abuse-control mechanism.
- Static parsing does not inspect scripts after browser execution.
- Allowing subdomains may substantially broaden crawl scope.
- A target can serve different content by validated IP, Host, geography or user agent.
- PageSpeed availability, quotas and response schemas are outside this service's control.

## Deployment checklist

1. Keep `SEO_ALLOW_PRIVATE_HOSTS=false`.
2. Set a strong `SEO_API_KEY` or enforce stronger gateway authentication.
3. Terminate TLS and apply per-client rate/body/time limits at the proxy.
4. Keep the Compose port on loopback or an internal network.
5. Apply egress filtering and isolate the runtime from cloud/server metadata networks.
6. Set conservative fetch, crawl and concurrency budgets for available capacity.
7. Configure only required CORS origins.
8. Keep dependencies and base images patched; review Dependabot and CI results.
9. Avoid logging query strings or request headers at the proxy.
10. Test private-IP, redirect and oversized-response rejection after infrastructure changes.

For vulnerability reporting, follow the root [security policy](../SECURITY.md).
