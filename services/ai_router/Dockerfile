ARG PY_IMAGE=python:3.12-slim-bookworm

# Stage 1: Build wheels
FROM ${PY_IMAGE} AS builder
WORKDIR /build
COPY requirements.txt .
RUN pip wheel --no-cache-dir -r requirements.txt -w /wheels

# Stage 2: Runtime
FROM ${PY_IMAGE} AS runtime
ENV DEBIAN_FRONTEND=noninteractive

RUN groupadd -r appgroup \
    && useradd -r -g appgroup -m -d /home/appuser \
       -s /usr/sbin/nologin appuser

WORKDIR /app

COPY --from=builder /wheels /wheels
COPY requirements.txt .
RUN pip install --no-cache-dir --no-index \
    --find-links=/wheels -r requirements.txt \
    && rm -rf /wheels

COPY model/model.joblib ./model/

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY --chown=appuser:appgroup app/ ./app/

USER appuser
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s \
    --start-period=5s --retries=3 \
    CMD python -c \
    "import sys,urllib.request; \
     urllib.request.urlopen( \
       'http://127.0.0.1:8000/health', timeout=2 \
     ); sys.exit(0)"

CMD ["gunicorn", "app.main:app", \
    "--bind", "0.0.0.0:8000", \
    "--workers", "2", \
    "--worker-class", "uvicorn.workers.UvicornWorker", \
    "--no-control-socket", \
    "--access-logfile", "-", \
    "--error-logfile", "-"]
