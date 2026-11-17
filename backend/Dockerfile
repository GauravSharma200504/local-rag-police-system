FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 HF_HOME=/models/hf

# Tesseract OCR with English + Hindi language data
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng tesseract-ocr-hin \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/backend
COPY backend/requirements.txt backend/requirements-ml.txt ./
RUN pip install -r requirements.txt \
    && pip install torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install -r requirements-ml.txt

COPY backend/ /app/backend/
COPY evaluation/ /app/evaluation/
COPY sample_data/ /app/sample_data/
COPY scripts/ /app/scripts/

RUN useradd --create-home --uid 1000 bpi && mkdir -p /app/data /models/hf && chown -R bpi /app /models
USER bpi
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
