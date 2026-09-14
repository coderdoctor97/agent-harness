---
name: docker-containerization
description: "Author minimal multi-stage non-root Dockerfiles with pinned digests, and reproducible compose environments that mirror production."
---

# Docker Containerization

## 1. Scope & Objective
- Containerize services: minimal, secure, reproducible images plus local compose environments that mirror the production configuration surface.
- In scope: Dockerfiles, `.dockerignore`, compose files, image size and security posture.
- Out of scope (delegate): cluster/orchestration provisioning → `iac-provisioning`; CI build pipelines → `cicd-pipeline-author`.

## 2. Trigger Conditions
- Commands: "containerize X", "review this Dockerfile", "the image is 2 GB", "local env doesn't match staging".
- Intent patterns: new service onboarding; image size or security findings; flaky local development.
- Orchestration tags: `infra:container`, `infra:compose`, `gate:image`.

## 3. Core Directives & Standards
1. **Multi-stage builds:** separate builder and runtime stages; runtime stage contains only what runs (no compilers, no dev deps).
2. **Non-root runtime user** in every image; base images pinned by digest (distroless/alpine/slim class); final image within a size budget (default ≤ 150 MB for a service, justified exceptions documented).
3. **Reproducibility:** pinned toolchain versions in the build; no network access needed at runtime stage; `.dockerignore` at least as strict as `.gitignore` (no `.env`, no VCS metadata, no local data).
4. **Healthchecks defined** (and used by orchestrators); no `latest` tags anywhere; no secrets via `--build-arg`.
5. **Compose mirrors prod:** service names, ports, env var names, and volumes match production surfaces so "works in compose" is meaningful.

## 4. Execution Workflow
1. **Intake & Analysis:** Identify runtime dependencies and OS requirements; measure the current image (size, layers, user, exposed ports); list the gap between compose and prod config.
2. **Implementation:** Rebuild the Dockerfile stage-by-stage (builder → runtime); add non-root user, healthcheck, pin digests; harden `.dockerignore`; align compose with prod config surface.
3. **Validation:** Image builds reproducibly (same digest for same inputs); `docker history` audit: no secrets, no unnecessary layers, non-root verified (`docker run --entrypoint id`); compose brings the full environment up under 3 minutes with healthchecks green.

## 5. Antipatterns & Prohibited Behaviors
- `COPY . .` without a strict `.dockerignore`.
- Running package installs in the final stage (or shipping a full dev toolchain in runtime).
- Default root user "because it's simpler".
- `latest` base tags or unpinned digests.
- Secrets passed as build args (persisted in image history).

## 6. Definition of Done & Quality Guardrails
- Size budget met (or exception documented); `docker history` audit clean (0 secrets, non-root).
- Compose environment parity: env var names/ports/volumes match prod (diff documented).
- Healthcheck passes under load and fails when the service is broken (negative test).
- Full local environment up in under 3 minutes from a clean state.
