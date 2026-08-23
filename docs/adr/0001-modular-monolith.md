# ADR 0001: Begin with a modular monolith

- Status: accepted
- Date: 2026-08-23

## Context

Chakravyuh needs independently runnable API and worker processes, but its payment invariants and action contracts must remain identical. Splitting an early implementation into separately deployed services would add network failure modes and version skew before product boundaries are stable.

## Decision

Use one Python package with strict domain, application, infrastructure, API, and worker modules. Deploy the API and worker as separate processes from the same artifact.

## Consequences

- Domain behavior has one version and one test suite.
- Process isolation remains available for scaling and failure containment.
- Application ports preserve the ability to extract a service later.
- Module boundaries require review discipline because the language does not enforce deployment boundaries.

