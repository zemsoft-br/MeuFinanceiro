FROM python:3.13.14-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --home-dir /app app

WORKDIR /workspace

COPY packages/finance/pyproject.toml ./packages/finance/
COPY packages/finance/src ./packages/finance/src
COPY packages/security/pyproject.toml ./packages/security/
COPY packages/security/src ./packages/security/src
COPY packages/persistence/pyproject.toml ./packages/persistence/
COPY packages/persistence/src ./packages/persistence/src
COPY apps/worker/pyproject.toml ./apps/worker/
COPY apps/worker/worker ./apps/worker/worker
RUN python -m pip install \
    ./packages/finance \
    ./packages/security \
    ./packages/persistence \
    ./apps/worker

WORKDIR /app
USER app
EXPOSE 8081

CMD ["python", "-m", "worker.main"]
