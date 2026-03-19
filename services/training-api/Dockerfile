ARG PY_IMAGE=python:3.12-slim-bookworm
FROM ${PY_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

RUN chown -R appuser:appuser /app

EXPOSE 8000

USER appuser

ENTRYPOINT ["python", "-m", "app.cli"]
CMD ["server"]
