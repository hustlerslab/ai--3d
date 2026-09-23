# P0-INFRA-001 — Evidence: container image and CI

**Completed 2026-09-21.** Allure can be deployed the same way twice, and a regression is caught before merge.

---

## Acceptance criteria

| Criterion | Result | How |
|---|---|---|
| **The container boots and serves `/api/health`** | ✅ | Built and run locally. **200 after 5 s.** |
| CI runs the MOCK suite | ✅ | `.github/workflows/ci.yml`, `backend` job |
| **CI output labels the test class (`class=MOCK`)** | ✅ | job name, `::notice`, step summary, and the artifact name |
| `docker build` succeeds | ✅ | **real build on this machine**, 71 MB, 11 layers |
| CI runs on push and blocks merge | ✅ | `on: [push (all branches), pull_request]`; three jobs, any failure fails the run |

## The build, actually run

Docker Desktop was not running; I started it and built for real rather than asserting the file was correct.

```
docker build -t allure-backend:local -f Dockerfile .
  ...
  naming to docker.io/library/allure-backend:local
  DONE 20.3s

docker image inspect
  size: 71386224 bytes (11 layers)   user: allure
```

## The container, actually probed

```
/api/health -> 200 after 5s

GET /api/health      (anonymous)  200   <- a probe must work without credentials
GET /api/projects    (anonymous)  401   <- P0-SEC-002 is in force inside the image
GET /files/assets-web/x.glb (anon) 401  <- P0-SEC-005 is in force inside the image
```

The last two matter more than the first. A container that boots but ships without its authorization gate is worse than one that does not boot, because it looks fine. The CI `image` job asserts the 401 as a build-blocking step for exactly this reason.

## No secret in the image

```
ls -a /app  ->  . .. app blender data pytest.ini requirements.txt
no .env in the image
```

`.dockerignore` keeps `**/.env`, `aether-backend/data/`, `**/*.db`, `.venv` and `node_modules` out of the **build context**, so they cannot enter a layer at all. That distinction is the point: an image layer is permanent, and a later `RUN rm` does not remove a file from the layer that added it.

## The CI guard, tested both ways

CI must never spend money. That is not left to the suite's good manners — a step asserts it, and the assertion is on the **value**, not on whether the variable is defined:

```
keys blank   ->  class=MOCK: no provider key is set; this run cannot spend a credit.
GEMINI_API_KEY set ->  REFUSING TO RUN: GEMINI_API_KEY is set.   (exit 1)
```

## Three deliberate omissions

| Not in the image | Why |
|---|---|
| **Blender** | ~1 GB. Bundling it would quadruple the image so every bug-fix deploy re-ships an unchanged renderer. The container reads `BLENDER_PATH` as the local process does; empty means render jobs fail with the clear error they already give, and Blender tests skip rather than lie. A render worker is a separate artifact (P3-INFRA-001). |
| **The frontend** | Next.js builds and deploys on its own; coupling them would make a CSS change wait on a Python test run. |
| **Postgres / Redis / a worker in compose** | None exists yet — `AUTH_PLAN.md` steps 6–7 are explicitly deferred. Four containers to exercise one is a cost paid by every developer for a future that has not arrived. |

## The deployment step this task carries

`docker-compose.yml` ends with it, in the file rather than in someone's memory:

> P0-SEC-002 gives the **first** account created on an instance administrator rights, so it can adopt projects that predate the users table. On a laptop that is the operator. On a reachable host it is a race. **Create the first account before the port is reachable by anyone else.**

It also pins `INTELLIGENCE_PROVIDER` (P0-AI-001 — never `auto`), ships the spend caps on (P0-SEC-003), and records that the rate limiter is in-process and therefore correct for **one** replica (P0-SEC-006).

## Not verified here, and why

**The workflow has not run on GitHub.** It parses (`yaml.safe_load` → 3 jobs, steps enumerated) and every command in it was run locally, but "a CI run on a pull request" needs a push to a remote, which is the owner's call and not mine to make. The evidence above is a local build and boot, not a green check on a PR.
