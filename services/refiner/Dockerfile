FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py prompts.py ./

RUN chown -R appuser:appuser /app && \
    mkdir -p /data && chown -R appuser:appuser /data

USER appuser

CMD ["python", "app.py"]
