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
COPY packages/banking/pyproject.toml ./packages/banking/
COPY packages/banking/src ./packages/banking/src
COPY packages/banking-pluggy/pyproject.toml ./packages/banking-pluggy/
COPY packages/banking-pluggy/src ./packages/banking-pluggy/src
COPY packages/security/pyproject.toml ./packages/security/
COPY packages/security/src ./packages/security/src
COPY packages/persistence/pyproject.toml ./packages/persistence/
COPY packages/persistence/src ./packages/persistence/src
COPY packages/banking-pluggy-execution/pyproject.toml ./packages/banking-pluggy-execution/
COPY packages/banking-pluggy-execution/src ./packages/banking-pluggy-execution/src
COPY apps/api/pyproject.toml ./apps/api/
COPY apps/api/app ./apps/api/app
RUN python -m pip install \
    ./packages/finance \
    ./packages/banking \
    ./packages/banking-pluggy \
    ./packages/security \
    ./packages/persistence \
    ./packages/banking-pluggy-execution \
    ./apps/api

WORKDIR /app
USER app
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
