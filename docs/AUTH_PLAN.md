# Auth and authorization — plan

**Status:** proposed · decision open · **no implementation code written**
**Written:** 11 Sep 2026
**Blocks:** any feature handling a real designer account, a real client's
project, or a real payment.

## The finding that has to come first

The question posed was "is this still meant to be Supabase (Postgres + Auth +
RLS) as originally scoped, or has that decision changed?"

**It was never Supabase in any recorded decision.** Supabase appears in zero
design documents and zero codebases on this machine. What the documents actually
say:

| Source | What it records |
|---|---|
| `docs/ALLURE_HYBRID_LOCAL_PLAN.md` (this repo) | Hosted shape is "API gateway, JWT, CDN, GPU workers"; database **PostgreSQL**; auth explicitly deferred to the hosted phase; "job rows are the migration seam" |
| `AETHER_SYSTEM_DESIGN_V2.md` | **PostgreSQL**; "authenticated project access"; "authorization checked" |
| `CODEBASE/decisions.md` | **ADR-001: minimal HS256 JWT** using Node's built-in `crypto`, deliberately avoiding a `jsonwebtoken` dependency. ADR-002: JWT in `sessionStorage` for the demo, with a stated migration path to httpOnly cookies |
| `CODEBASE/backend-architecture.md` | "JWT-based auth with refresh tokens; integrate a simple RBAC for designer/admin roles" |

So the recorded direction is **PostgreSQL + self-hosted JWT + RBAC**, and a JWT
implementation already exists in the sibling `CODEBASE` project. Nothing was
"changed" — the Supabase framing entered through a prompt, not a decision
record. This plan is written against the documents. If Supabase *is* now the
intent, that is a new decision and should be recorded as one rather than assumed.

## What exists today

`aether-backend` is SQLite with **no auth layer of any kind**: no users table, no
session, no principal, no tenant column, no `GRANT`, no policy mechanism. Eight
tables (`meta, projects, inputs, analyses, scene_specs, jobs, events, outputs`).
Every route is reachable by anyone who knows a `project_id`. This is recorded in
`docs/ALLURE_HYBRID_LOCAL_PLAN.md` as deliberate for local mode — it is not an
oversight, it is an un-started phase.

## Three things about this codebase that a generic "add RLS" plan would miss

These are why this plan is worth reading rather than copying a template.

**1. Row-level security cannot protect most of the product's data.** Scenes are
**JSON files on disk**, not rows — `data/projects/{id}/` holds the analysis, the
plan, the scene spec, the renders and the tour package.
`GET /files/projects/{id}/{path}` serves them today with a path-traversal guard
and **no authorization whatsoever**. `/files/assets` and `/files/materials` are
`StaticFiles` mounts. RLS reaches none of it. Whatever is chosen, file
authorization is application-layer work — and it is the largest hole, larger than
the database one.

**2. The job runner has no user context.** It is an in-process thread pool that
resumes work after a restart. It cannot carry a user's JWT, so it needs a service
identity. Under Supabase that means the service role — which bypasses RLS — so a
meaningful fraction of all writes would bypass RLS by construction.

**3. Share links are deliberately anonymous.** `/w/{projectId}` is a public
read-only tour. That is a feature, not a gap. It needs a **capability token** —
unguessable, revocable, scoped to one project's tour package — not a user
session. An auth rollout must not quietly break or over-restrict it.

Together: even with Supabase, most of the authorization surface would still be
app-layer. RLS is worth having as defence-in-depth. It is not worth choosing a
vendor for.

## The decision, scoped both ways

### Option A — Supabase (Postgres + GoTrue + RLS)

Fastest to stand up; auth, storage and policies in one product.

The catch specific to this codebase: the backend is **FastAPI**, not Supabase
edge functions. For `auth.uid()` to resolve inside a policy, the backend must
connect to Postgres **as the end user**, forwarding their JWT per request — which
fights connection pooling and cannot work for the job runner. The usual
alternative is to connect with the service role and authorize in the application,
at which point RLS is decorative. It also adds vendor coupling to a product whose
stated architectural discipline is swappable vendors.

### Option B — Postgres + self-hosted JWT + RBAC *(matches the recorded ADRs)*

What the documents already decided, with an implementation already written in the
sibling project. No vendor coupling. `app/db/sqlite.py` is documented as the swap
seam and is genuinely structured as one.

Cost: you own auth's security — registration, login, refresh rotation, password
reset, lockout, and every mistake in that surface.

### Option C — Postgres + managed identity provider, authorization in the app

Keep Postgres neutral and self-hosted; outsource only the part that is dangerous
to build (identity, sessions, password reset, MFA); authorize at one choke point
in FastAPI; add RLS later as defence-in-depth.

**Recommendation: C, with B as the fallback if an external identity provider is
unacceptable.** The three findings above mean app-layer authorization is
unavoidable either way, so the question reduces to *who implements identity*.
Building identity yourself is the highest-risk, lowest-differentiation work in
the product. Option A's headline benefit — RLS — is substantially neutralised
here by the file storage and the job runner.

**This is the open decision and it is not mine to make.** Everything below holds
for B and C alike, and mostly for A.

## Data model

New tables:

| Table | Purpose |
|---|---|
| `users` | `user_id`, `email`, `role`, `created_at`; plus `password_hash` (B) or `external_id` (A/C) |
| `project_members` | `project_id`, `user_id`, `role` — the sharing/assignment join |
| `capability_tokens` | `token_hash`, `project_id`, `scope`, `expires_at`, `revoked_at` — powers share links and signed file access |
| `audit_log` | who did what, to which project, when |
| `refresh_tokens` | option B only |

Changed: `projects` gains `owner_id`. Note `projects` **already has a migration
ladder** (`MIGRATIONS` in `app/db/sqlite.py`, added with the verticals feature),
so adding a column is now a one-tuple append rather than a redesign.

Roles: `homeowner` (owns projects), `designer` (assigned to projects), `admin`
(all). Deliberately three, not a permission matrix — widen only when a real
requirement appears.

## Authorization rules

Expressed once as app-layer rules; RLS policies, if added, mirror them.

| Actor | Projects | Files | Jobs |
|---|---|---|---|
| homeowner | own only (`owner_id`) | own project's outputs | enqueue on own |
| designer | assigned via `project_members` | assigned projects' files | enqueue on assigned |
| admin | all | all | all |
| share-link holder | one project, read-only, tour package only | that project's tour assets only | none |
| job runner | service identity, all | all | — |

## Rollout sequence

Ordered so each step ships independently, and nothing is enforced before the data
exists to enforce it against.

0. **Record the decision** (A/B/C) as `ADR-002`. Everything below depends on it.
1. **Data model first, no enforcement** — `users`, `project_members`, `owner_id`;
   still SQLite, still open. Backfill existing projects to a single owner.
2. **Authentication at the edge** — login/session, and a FastAPI dependency that
   yields the current principal. Still no enforcement.
3. **Authorization at one choke point** — a single dependency every project route
   passes through. Deny by default. This is the step that actually closes the
   hole.
4. **File authorization** — replace the bare `/files/projects/...` route and the
   two `StaticFiles` mounts with authorized or signed access. Largest single
   gain, and independent of the database choice.
5. **Share links as capability tokens** — unguessable, revocable, tour-scoped.
6. **SQLite → Postgres** — `app/db/sqlite.py` is the seam; the stores above it
   should not change.
7. **RLS as defence-in-depth** — mirror the step-3 rules. Needs a per-request
   session variable (`SET LOCAL`) or per-user connections; the job runner keeps a
   service identity and bypasses.

Steps 1–5 deliver most of the security benefit and are independent of the
database decision. Only 6 and 7 depend on it — so **the A/B/C decision does not
block starting.**

## Explicitly not in this plan

- **Billing.** There is no credits system, no ledger, no Razorpay and no
  subscription tier anywhere in this codebase. Payments need their own plan, and
  must not be designed into the auth schema speculatively.
- **Implementation.** No code has been written for any of this, by intent.
- **Multi-tenancy beyond project membership.** Studios/organisations may be
  needed later; not designed for now.
