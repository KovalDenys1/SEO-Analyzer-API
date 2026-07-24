# Security policy

## Supported versions

Security fixes are provided for the latest release on the `main` branch.

| Version | Supported |
|---|:---:|
| Latest | Yes |
| Older releases | No |

## Reporting a vulnerability

Do not open a public issue for an undisclosed vulnerability. Use GitHub's **Report a vulnerability** flow in the Security tab of this repository to submit a private security advisory.

Include the affected commit/version, reproduction steps, expected impact and any suggested mitigation. Do not include credentials or data that you are not authorized to share.

The maintainer will acknowledge the report, assess severity, coordinate a fix and publish disclosure details after users have had a reasonable opportunity to update. Reporter credit is optional.

## Scope

Reports about SSRF bypasses, redirect/DNS rebinding, response-budget bypasses, authentication mistakes, secret disclosure, unsafe XML/HTML handling and dependency vulnerabilities are especially useful. General SEO disagreements or target-site availability problems should use normal issues.

See [the security model](docs/SECURITY.md) for architecture, residual risks and deployment guidance.
