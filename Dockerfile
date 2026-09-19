# Cloud Run image for the Kagaz web UI.
#
# Runs both flows: the synthetic demo (served from the committed fixtures
# in replay mode) and the real-account flow (which forces live model calls
# in code, regardless of KAGAZ_LLM_MODE — see agents/coordinator.py's
# run_real_audit_with_escalation). Credentials come from the Cloud Run
# runtime service account via Application Default Credentials; no key file
# is ever built into this image.

FROM python:3.12-slim

# pdfplumber/Pillow/reportlab need no system packages beyond these for the
# formats this app handles; keeping the list minimal keeps the image small.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libglib2.0-0 libgl1 \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . .

# Cloud Run injects PORT and expects the container to listen on it.
ENV PORT=8080
CMD exec uvicorn api.main:app --host 0.0.0.0 --port ${PORT}
