ARG PY_IMAGE=python:3.12-slim-bookworm
FROM ${PY_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN groupadd -r appuser && useradd -r -g appuser -d /train -s /sbin/nologin appuser

WORKDIR /train

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY train.py .

RUN chown -R appuser:appuser /train && \
    mkdir -p /model && chown -R appuser:appuser /model

USER appuser

CMD ["python", "train.py", \
    "--data", "./train.csv", \
    "--out", "/model/model.joblib", \
    "--metrics", "/model/metrics.json", \
    "--misclassified", "/model/misclassified.csv"]
