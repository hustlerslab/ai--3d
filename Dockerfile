# Allure backend — P0-INFRA-001
#
# What this image is, and what it deliberately is not.
#
# **It is the API.** FastAPI, the job runner, SQLite, the asset registry.
#
# **It is NOT Blender.** The render lane shells out to a Blender binary, and a
# Blender install is roughly 1 GB — bundling it would quadruple the image so
# that every deploy of a bug fix re-ships a renderer that did not change. The
# container reads BLENDER_PATH like the local process does; where that path is
# empty, render jobs fail with the same clear error they already give, and the
# tests that need it skip rather than lie. A render worker image is a separate
# artifact (task.md P3-INFRA-001, separability).
#
# **It is NOT the frontend.** Next.js builds its own bundle and deploys on its
# own; coupling the release cycles would make a CSS change wait on a Python
# test run.

FROM python:3.12-slim AS base

# PYTHONDONTWRITEBYTECODE: a read-only filesystem is a reasonable thing to want
#   later, and .pyc files baked into a layer are noise.
# PYTHONUNBUFFERED: without it the logs of a container that dies are lost in the
#   buffer — which is exactly when they are needed.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Requirements first, as their own layer: application code changes on every
# commit and dependencies change monthly, so this keeps the slow step cached.
COPY aether-backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY aether-backend/app ./app
COPY aether-backend/blender ./blender
COPY aether-backend/pytest.ini ./pytest.ini

# Runs as a non-root user. The data directory is created and owned before the
# switch: a container that cannot write its own database should fail at the
# first request, not silently at some later write.
RUN useradd --create-home --uid 10001 allure \
    && mkdir -p /app/data \
    && chown -R allure:allure /app
USER allure

ENV AETHER_DATA_DIR=/app/data \
    AETHER_HOST=0.0.0.0 \
    AETHER_PORT=8000

EXPOSE 8000

# /api/health is deliberately anonymous (authz.ANONYMOUS_EXACT) precisely so a
# probe works without credentials. A health check that needs a session reports
# the wrong thing during exactly the outage it was written for.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
