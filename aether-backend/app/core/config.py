"""Aether walkthrough backend configuration.

All settings come from environment variables / .env. API keys are SecretStr
and are only unwrapped inside provider adapters.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    aether_host: str = "127.0.0.1"
    aether_port: int = 8000
    aether_cors_origins: str = "http://localhost:3000,http://localhost:3001"
    aether_data_dir: str = "./data"

    # Which LLM drives the intelligence layer: auto | anthropic | gemini | ollama | mock.
    # auto = Claude when ANTHROPIC_API_KEY is set, else Gemini when GEMINI_API_KEY is set, else mock.
    # `ollama` is never chosen by auto: it is local and free but slower and
    # weaker, so it has to be asked for.
    intelligence_provider: str = "auto"

    # ── Ollama (local, no API key) ──────────────────────────────────────
    # Runs on the same GPU as Blender, so when this provider is selected the
    # runner moves the stages that call it onto the render lane — one GPU
    # consumer at a time. See JobRunner._lane_for.
    ollama_base_url: str = "http://127.0.0.1:11434"
    # 3b, not 7b, and the reason is the card rather than the model: qwen2.5vl:7b
    # at q4 is ~6 GB of weights alone, so on a 6 GB GPU ollama reported 6.9 GB
    # and split 50/50 with the CPU — a 90 s call became over ten minutes. The 3b
    # runs 100% on GPU at 3.4 GB with the full context and reads all the photos.
    ollama_model: str = "qwen2.5vl:3b"
    ollama_timeout_seconds: int = 900
    # Sized to the VRAM, not to ambition. Measured on the 8-photo sample set at
    # 512 px: the request is ~12.7k tokens (+~1.1k for the analysis prompt), so
    # an 8k window 400s. 24k does fit the tokens but NOT the card — ollama
    # reported 7.1 GB and ran 69%/31% CPU/GPU, which turned a 90 s call into
    # over ten minutes. 16k holds the whole request, stays wholly on the GPU
    # (measured 4.8 of 6.1 GB) and is the largest window that does.
    ollama_num_ctx: int = 16384
    # qwen2.5-VL bills context by pixel area. Full-size photos are ruinous —
    # four originals crashed llama-server with a stack overrun. 512 px fits all
    # eight photos and still distinguishes a sofa from a mattress.
    ollama_image_max_px: int = 512
    ollama_max_images: int = 8
    # Reading ONE approved render is a different budget from reading eight
    # reference photos. The 512 px above exists because eight photos at 1024 px
    # cost ~11.6k image tokens and did not fit the window; a single render at
    # 768 px costs a fraction of that and leaves the 16k context mostly free.
    # It matters because this read has to produce tight bounding boxes, and a
    # 704x448 render thumbnailed to 512 px throws away detail the box needs.
    ollama_scene_image_max_px: int = 768
    # Ollama's default output cap truncated the analysis mid-string at ~23 KB
    # of JSON, which then fails to parse and throws the whole call away. The
    # analysis schema is large (up to 40 spotted objects), so it needs room.
    ollama_num_predict: int = 8192

    gemini_api_key: SecretStr = SecretStr("")
    # Google retires ids quickly; the fallback list is tried on 404/429/503.
    # lite answers a vision stage in 2-6 s; the full flash models are the fallback for quality/outages
    gemini_model: str = "gemini-3.5-flash-lite"
    gemini_fallback_models: str = "gemini-3.6-flash,gemini-3.5-flash,gemini-flash-lite-latest,gemini-2.5-flash"
    # 60 s was enough until the object planner started carrying the asset
    # library (~5 KB) in its prompt; measured timeouts on plan_objects at 60,
    # clean runs at 180. The fallback to the mock hides this as a quietly worse
    # plan rather than an error, so the headroom matters.
    gemini_timeout_seconds: int = 150
    # How many reference photos may ride along on one vision call. Was a
    # hardcoded 6 inside the provider while uploads allowed 12, so two of a
    # client's eight references silently never reached the model. Measured
    # (research/p11_reference_capacity.py, docs/benchmarks/
    # p11_reference_capacity.json): 6/8/10/12 all return HTTP 200 with valid
    # JSON, costing ~1.1 k prompt tokens per image and 15.1 k in total at 12 -
    # nowhere near the model's context, so the old cap was never a token
    # limit. Set to MAX_REFERENCES so no upload is ever dropped. Attribute
    # extraction does thin out as images pile up on ONE call, which is why
    # per-reference classification (app/intelligence/reference_reader.py)
    # reads each photo on its own rather than trusting this batch.
    gemini_max_reference_images: int = 12

    # ── Moodboard scene image (local Stable Diffusion) ──────────────────
    # Replaced the Gemini image path, which needs billing: every image model
    # answers 429 with `limit: 0` on a free-tier key. This runs on the GPU for
    # nothing. A failure degrades the moodboard, never fails the analysis.
    scene_image_enabled: bool = True
    scene_image_model: str = "runwayml/stable-diffusion-v1-5"
    # Landscape, not square, and this is the single biggest lever on whether
    # the moodboard reads as a room. A square frame invites the model to centre
    # one object and fill it — measured over three seeds, every 512x512 render
    # came back sofa-dominant while the same prompt and seed at 704x448 gave a
    # furnished room with seating, coffee table, rug and two walls. Interior
    # photography is landscape; the frame was fighting the prompt.
    # 704x448 is a multiple of 64 (SD 1.5 needs that), ~20% more pixels than
    # 512x512, and still fits beside Blender and Ollama on a 6 GB card.
    scene_image_width: int = 704
    scene_image_height: int = 448
    scene_image_steps: int = 28
    # IP-Adapter strength: 0 ignores the client's photo, 1 copies it so hard the
    # prompt stops mattering. At 0.6 the render drifts towards a product shot of
    # the reference — the piece is faithful and the room is gone. 0.35 buys the
    # room back and pays for it in fidelity: measured over six renders (sofa and
    # bed, three seeds each) every one read as a room, while the reference's
    # colour carried strongly, partly, or not at all depending on the seed.
    # That trade is deliberate — see docs/ADR-002-scene-reference.md.
    scene_image_reference_scale: float = 0.35

    anthropic_api_key: SecretStr = SecretStr("")
    anthropic_model: str = "claude-opus-5"
    anthropic_timeout_seconds: int = 90

    meshy_api_key: SecretStr = SecretStr("")
    meshy_base_url: str = "https://api.meshy.ai"
    # How long to wait for one mesh. Raised from 300 s, which was under the
    # vendor's own worst case and so read as a failure when it was only
    # slowness: measured in one batch, two pieces were abandoned "still
    # IN_PROGRESS at 45% after 300s" while four others in the same batch
    # finished. Abandoning at 45% wastes the wait and leaves a stand-in in the
    # room; waiting costs only time, and the poll is cheap.
    meshy_timeout_seconds: int = 900
    # preview = geometry only (cheap, ~75 s). refine adds textures for a second
    # charge against the same task; preview is the default because the planner
    # already supplies a colour and the stand-in being replaced is untextured.
    meshy_mode: str = "preview"
    meshy_art_style: str = "realistic"
    # Measured: remesh off returns ~1.9 M triangles, past the ingester's hard
    # limit, so the asset registers as `failed` and cannot be used. On, at 30k,
    # it passes and the glb is 42x smaller. Do not turn this off casually.
    meshy_should_remesh: bool = True
    meshy_target_polycount: int = 30_000
    # Generation costs credits, so a runaway plan must not drain the account.
    # Per project, not per job: a re-run resumes from checkpoints and never
    # re-spends on a piece already generated.
    #
    # Raised from 6, which sat below the size of an ordinary room and so acted
    # as a silent truncation rather than a safety rail: measured on a single
    # living room, 11 approved pieces became "5 over the limit of 6" in a job
    # event nobody reads, and five pieces stood in the finished 3D space as
    # catalog stand-ins with nothing on screen saying why. A cap still exists -
    # a plan cannot drain the account - but it now sits above a real room.
    meshy_max_per_project: int = 20
    meshy_poll_seconds: float = 10.0
    # P1-ASSET-003 - how many generation tasks may be in flight at the vendor at
    # once. Meshy queues are per ACCOUNT across every API key: 10 on Pro, 30
    # Premium, 20 Studio, 100 Ultra (docs.meshy.ai/en/api/rate-limits). Past
    # that, every submission is 429 NoMoreConcurrentTasks. 8 sits under the
    # Pro queue with room for a task the dashboard started by hand; raise it
    # to match the plan, never above it.
    meshy_max_concurrent_tasks: int = 8

    # P0-SEC-003 - spend caps in CREDITS, checked against the persisted ledger
    # rather than a counter in memory. `meshy_max_per_project` above is a
    # different thing: it limits how many pieces ONE job may attempt, resets
    # with every new job, and so cannot bound total spend.
    #
    # 600 credits is 20 pieces at 30 each - the same ceiling the per-job limit
    # implies, now enforced across every job for the life of the project.
    # 3000 per user is 100 pieces: generous for one person, ruinous for none.
    # Set either to 0 to run deliberately uncapped; that is a choice a
    # deployment makes explicitly, never a default.
    meshy_max_credits_per_project: int = 600
    meshy_max_credits_per_user: int = 3000

    # P0-SEC-006 - rate limits, per bucket, per window. A value of 0 disables
    # that bucket; setting rate_limit_enabled=false disables all of them, which
    # is the documented rollback. Reads are deliberately generous: a limit that
    # fires during normal studio use trains people to reload harder.
    rate_limit_enabled: bool = True
    rate_limit_window_seconds: int = 60
    rate_limit_auth_per_window: int = 10      # password guessing lives here
    rate_limit_spend_per_window: int = 5      # anything that costs Meshy credits
    rate_limit_write_per_window: int = 60
    rate_limit_read_per_window: int = 300

    provider_fallback_to_mock: bool = True

    # ── Blender (hybrid local pipeline) ─────────────────────────
    # Path to the blender executable (portable build). Empty = not configured;
    # render-lane jobs then fail fast with BLENDER_NOT_CONFIGURED.
    blender_path: str = ""
    blender_timeout_seconds: int = 1800

    # ── Job runner ──────────────────────────────────────────────
    # Two lanes: "ai" (network-bound agents) and "render" (owns the GPU).
    jobs_ai_workers: int = 2
    jobs_render_workers: int = 1
    jobs_retry_delay_seconds: float = 2.0
    jobs_default_max_attempts: int = 3

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.aether_cors_origins.split(",") if o.strip()]

    @property
    def data_dir(self) -> Path:
        path = Path(self.aether_data_dir).resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def db_path(self) -> Path:
        return self.data_dir / "allure.db"

    @property
    def projects_dir(self) -> Path:
        path = self.data_dir / "projects"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def repo_root(self) -> Path:
        return Path(__file__).resolve().parents[2]

    @property
    def blender_scripts_dir(self) -> Path:
        return self.repo_root / "blender" / "scripts"

    @property
    def blender_configured(self) -> bool:
        return bool(self.blender_path) and Path(self.blender_path).exists()

    @property
    def gemini_configured(self) -> bool:
        return bool(self.gemini_api_key.get_secret_value())

    @property
    def meshy_configured(self) -> bool:
        return bool(self.meshy_api_key.get_secret_value())

    @property
    def anthropic_configured(self) -> bool:
        return bool(self.anthropic_api_key.get_secret_value())


@lru_cache
def get_settings() -> Settings:
    return Settings()
