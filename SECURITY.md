# Security

This is a personal research and portfolio project, maintained by one
person, without a dedicated security team or an SLA on response time.

## Reporting a vulnerability

Please do not open a public GitHub issue for a security concern. Use
GitHub's private vulnerability reporting instead:
[Report a vulnerability](https://github.com/MAndersonASU/real-time-recommendation-ranking-platform/security/advisories/new).

Include what you found, how to reproduce it, and its likely impact. A
fix will be prioritized over new feature work; a public advisory is
only published once a fix is available.

## Scope

This project's default configuration is intended for local,
single-machine development and demonstration use, not a shared or
production deployment. Known, disclosed limitations of that default
configuration (documented in `docs/configuration.md` and
`docker-compose.yml`) — for example, Kafka running without
authentication — are not considered vulnerabilities on their own; a
real bypass of an intended control, or an issue in application code
itself, is in scope.
