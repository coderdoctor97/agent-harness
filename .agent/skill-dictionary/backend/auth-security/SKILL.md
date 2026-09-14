---
name: auth-security
description: "Implement and harden authentication and authorization: token lifecycles, session invalidation, password hashing, and object-level RBAC/ABAC guards."
---

# Auth & Security

## 1. Scope & Objective
- Implement and harden the identity surface: token issuance/rotation, session lifecycle, password storage, and authorization enforcement (RBAC/ABAC) at the route and object level.
- In scope: login/logout/refresh flows, guards, role/permission models, credential storage parameters.
- Out of scope (delegate): system-wide threat assessment → `threat-model-sast`; transport/infra TLS; dependency CVEs → `security-cve-audit`.

## 2. Trigger Conditions
- Commands: "add login/SSO", "users can't access X", "review the permissions for Y", "the token flow is broken".
- Intent patterns: any PR touching identity, sessions, or access control; new resource types that need ownership checks.
- Orchestration tags: `auth:implement`, `authz:review`, `gate:auth`.

## 3. Core Directives & Standards
1. **Token lifecycle:** short-lived access tokens (≤ 15 min) with rotating refresh tokens and reuse detection; no stateless-JWT-without-revocation schemes for sensitive actions.
2. **Password storage:** Argon2id (or bcrypt cost ≥ 12) with parameters pinned in config — never home-rolled or legacy MD5/SHA.
3. **Default deny:** every authenticated route has an explicit guard; authorization is enforced server-side at the route *and* the object level (every fetched resource checks requester ownership or role — no client-side hiding).
4. **Session invalidation is a feature:** logout (and credential change/admin revocation) kills server-side session state; the invalidation path is tested.
5. **Safe comparisons:** constant-time comparison for secrets; no tokens or passwords in logs, error messages, or query strings.

## 4. Execution Workflow
1. **Intake & Analysis:** Map the flows (login, refresh, logout, SSO), token lifetimes, the role/permission matrix, and where authorization is currently enforced per route; list all resources with owner semantics.
2. **Implementation:** Token issuance + rotation with reuse detection; guard middleware (default deny); object-level checks in the resource layer; invalidation handlers; update hashing parameters.
3. **Validation:** Test matrix — expired token → 401; token reuse after rotation → rejected; user A cannot fetch/modify user B's resources (IDOR tests per resource type); logout invalidates (subsequent calls 401); no secrets in logs (log audit).

## 5. Antipatterns & Prohibited Behaviors
- Long-lived JWTs with no revocation and a "well, no one will wait 10 years" rationale.
- Client-side-only authorization (hiding the button instead of checking the server).
- `isAdmin` booleans living in client state.
- Timing-unsafe string comparison for secrets or signatures.
- Storing tokens where XSS can exfiltrate them, without an explicit review and mitigation.

## 6. Definition of Done & Quality Guardrails
- Token lifecycle tests pass (expiry, rotation, reuse detection, invalidation).
- Object-level access matrix tested for every owner-scoped resource type.
- Route inventory audited: 0 routes lacking an explicit guard.
- Hashing algorithm + parameters documented and verified in config; log audit shows 0 secrets.
