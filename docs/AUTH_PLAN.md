# Auth and authorization — plan

**Status:** **DECIDED 21 Sep 2026 — see "The decision, made" at the foot of this
document.** Neither A, B nor C: identity comes from the parent `CODEBASE`
project, which already has it. Everything above the decision section is kept as
written, because the analysis is what makes that choice coherent.
**Written:** 11 Sep 2026 · **Decided:** 21 Sep 2026
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

---

# The decision, made

**21 Sep 2026, by the owner.** Quoted, because a decision record that
paraphrases is a decision record nobody trusts:

> "right now we are not including the auth system because this code base is the
> part of other code base and other codebase have the proper auth part"
>
> "right now not linked i will link it further after this done"

## What was chosen

**Option D — identity is delegated to the parent `CODEBASE` project.** Allure
does not own accounts, passwords, sessions or password reset. This repository is
a component of a larger product that already authenticates people.

That closes the question this document opened. It is not a compromise between
A, B and C; it removes the premise. The reasoning that led to recommending C —
"building identity yourself is the highest-risk, lowest-differentiation work in
the product" — points the same way, only further: the best version of not
building identity is not building it *at all*.

## What this does NOT change

**Authorization stays here, and has to.** The distinction this document drew in
its three findings is exactly the one that matters now:

| | Whose job |
|---|---|
| *Who is this person?* | the parent codebase |
| *May this person open project `proj_x`?* | **Allure** |
| *May this person spend 30 Meshy credits?* | **Allure** |
| *May this link show this tour and nothing else?* | **Allure** |
| *May this request read `/files/projects/x/renders/…`?* | **Allure** |

The parent cannot answer any of the last four. It does not know which projects
exist, who owns them, what a tour package contains, or what a mesh costs. Those
are Allure's own data model, and `docs/production/v4_inventory.md` shows why
they cannot be inherited: 63 routes, 34 of them mutating, 2 able to spend money.

So P0-SEC-002 through P0-SEC-006 — ownership, spend caps, share links, file
authorization, rate limiting — remain correct and remain necessary. They were
never about who you are; they are about what you may do.

## The seam, and the size of the link

Everything outside `app/auth/` touches identity through **one type and two
functions**:

```python
from app.auth import Principal, require_principal, optional_principal
```

```python
@dataclass(frozen=True)
class Principal:
    user_id: str
    email: str
    role: str        # homeowner | designer | admin
```

Measured: **9 call sites in 2 files** — `app/api/projects_routes.py` (6) and
`app/main.py` (3). Everything else in the codebase asks the gate, never the
identity store.

**Linking therefore means replacing one function**, `auth.service.resolve_session`,
with whatever the parent hands over — a verified JWT, a trusted gateway header,
or a session lookup against its store — and mapping that to a `Principal`. The
authorization layer above it does not change.

## What becomes redundant on the day it is linked

| Now | On linking |
|---|---|
| `POST /api/auth/register`, `POST /api/auth/login` | **Delete.** The parent owns sign-up and sign-in. |
| `users.password_hash`, `scrypt` hashing | **Stops being written.** The column stays until a migration drops it, because dropping a column with data in it is its own task. |
| `users.external_id` | **Becomes the join** to the parent's user id. It was added nullable for exactly this reason. |
| `sessions` table, `POST /api/auth/logout` | Depends on the parent's mechanism. If it issues a JWT, this table stops being used; if it has server-side sessions, this becomes a cache of them. |
| `users` rows, `role`, `project_members` | **Stay.** Project membership is Allure's, not the parent's. |
| `require_principal`, `Principal`, the gate, spend caps, share links, file authorization, rate limiting | **Stay, unchanged.** |

## Why the local login was still worth building

Three reasons, stated so the decision does not read as wasted work:

1. **Nothing was reachable without it.** P0-SEC-002 closed 60 of 63 routes. A
   gate with no way to get through it is an outage, not a security control.
2. **It is the standalone development path.** Running Allure on its own — which
   is how every test in `tests/` runs, and how the container boots — needs some
   way to be somebody.
3. **It is the thing being replaced, so it defines the contract.** `Principal`
   exists because something had to produce one. The parent will produce the
   same shape.

The cost of the choice is one module, `app/auth/service.py`, and two routes.
The parts that survive — authorization, ownership, spend protection, capability
tokens, file access — are the parts that took the work.

## Still not in scope

Unchanged from the original plan: **billing** (no credits system, no ledger, no
subscription tier — `spend_records` tracks *provider cost*, not customer
billing), and **multi-tenancy beyond project membership**.
