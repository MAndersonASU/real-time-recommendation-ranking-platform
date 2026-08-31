# Security

This is a single-maintainer research and portfolio project. It has no
dedicated security team and no guaranteed response time.

## Reporting a vulnerability

Do not open a public issue for a security concern. Use
[GitHub's private vulnerability form](https://github.com/MAndersonASU/real-time-recommendation-ranking-platform/security/advisories/new).

Please include:

- what you found;
- a minimal reproduction;
- the likely impact; and
- any known workaround.

Security corrections take priority over new feature work. A public
advisory is published only after a correction is available.

## Scope

The default configuration is for local, single-machine demonstrations.
It is not a production deployment.

| In scope | Not a vulnerability by itself |
|---|---|
| A bypass of an intended security control | A limitation already disclosed for local use |
| A security defect in application code | Kafka running without authentication in the default local stack |
| Exposure that contradicts the documented configuration | The absence of production hardening that the project does not claim |

See [configuration](docs/operations/configuration.md) and
`docker-compose.yml` for the disclosed local defaults.
