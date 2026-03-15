ARG PY_IMAGE=python:3.12-slim-bookworm
FROM ${PY_IMAGE}
WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

EXPOSE 8000

# ENTRYPOINT + CMD: docker compose up runs server; docker compose run training-api train|refine|promote runs CLI
ENTRYPOINT ["python", "-m", "app.cli"]
CMD ["server"]
