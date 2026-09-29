# Container image for the Formly API.
# Used by Hugging Face Spaces (SDK: docker) and any other container host.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Hugging Face Spaces routes traffic to port 7860; other hosts inject $PORT.
ENV PORT=7860
EXPOSE 7860

# Single worker: generation is I/O-bound on a remote GPU, and the asset store is
# per-process, so a second worker could serve a 404 for another worker's asset.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-7860} --workers 1"]
