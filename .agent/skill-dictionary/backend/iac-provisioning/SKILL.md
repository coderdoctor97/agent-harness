---
name: iac-provisioning
description: "Provision cloud infrastructure declaratively (Terraform, Pulumi, SST) with locked remote state, policy checks, and secrets wired only by reference."
---

# IaC Provisioning

## 1. Scope & Objective
- Provision and evolve cloud infrastructure as code: resources, environments, state management, policy gates, and secure secret wiring.
- In scope: Terraform/Pulumi/SST modules and stacks, state handling, drift detection, secret references.
- Out of scope (delegate): application code; container images → `docker-containerization`; pipeline mechanics → `cicd-pipeline-author`.

## 2. Trigger Conditions
- Commands: "provision X", "new staging environment", "Terraform plan looks wrong", "we have drift in prod".
- Intent patterns: new environment; infrastructure change; unexplained resource differences; secret handling concerns.
- Orchestration tags: `infra:provision`, `infra:drift`, `gate:infra`.

## 3. Core Directives & Standards
1. **Remote, locked state:** state lives in a remote backend with locking enabled; two concurrent plans must conflict, not corrupt.
2. **Secrets by reference only:** values live in a secret manager (Vault/SSM/Secrets Manager); IaC references IDs — secrets never appear in state, plan output, or CLI variables.
3. **Plan → review → apply, pipeline-only:** humans review plans; applies happen in the pipeline with no manual-apply permission for production.
4. **Environment isolation and naming:** per-environment workspaces/stacks with strict naming and tags; destroy guards on production state.
5. **Drift is detected on a schedule** with alerting and a triage owner — drift is an incident signal, not background noise.

## 4. Execution Workflow
1. **Intake & Analysis:** Identify required resources, dependencies, blast radius, and the secrets needed; review the current state and any known drift.
2. **Implementation:** Author modules per concern; per-environment configuration; secret references; policy checks (Sentinel/OPA/Conftest) wired into the pipeline; destroy guards.
3. **Validation:** Plan diff reviewed against intent; apply to an isolated environment; drift scan clean (or each finding ticketed); lock verified by a concurrent-plan test; rollback path documented (which resources, in which order).

## 5. Antipatterns & Prohibited Behaviors
- Secrets in state files, plan output, or CI logs.
- `count` or `for_each` on environment selection (use workspaces/stacks).
- No destroy guard on production (one fat-fingered `destroy` ends the company's data).
- One giant flat file instead of modules (unreviewable, unshareable).
- Manual `terraform apply` to prod as normal operations practice.

## 6. Definition of Done & Quality Guardrails
- Applies are pipeline-only (no manual-apply permissions in the provider console/CI).
- State locking verified (concurrent plan test shows the conflict).
- Secret scan of state + plan output: 0 findings.
- Drift report clean, or every finding has a ticket with an owner.
