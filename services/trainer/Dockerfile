ARG PY_IMAGE=python:3.12-slim-bookworm
FROM ${PY_IMAGE}
WORKDIR /train

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY train.py .
COPY train.csv .

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

CMD ["python", "train.py", \
    "--data", "./train.csv", \
    "--out", "/model/model.joblib", \
    "--metrics", "/model/metrics.json", \
    "--misclassified", "/model/misclassified.csv"]
