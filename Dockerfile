FROM python:3.12-slim

# libgl1/libglib2.0-0: OpenCV (used by RapidOCR); libreoffice-impress: legacy .ppt → .pptx conversion.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libreoffice-impress \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /srv
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .

# Secrets (ANTHROPIC_API_KEY, TEN_APP_PASSWORD) are injected by Railway at runtime, never baked in.
EXPOSE 8501
CMD ["sh", "-c", "python -m streamlit run app/app.py --server.port ${PORT:-8501} --server.address 0.0.0.0 --server.headless true"]
