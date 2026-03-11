FROM python:3.12-slim

WORKDIR /app

# Dépendances système minimales
RUN apt-get update && apt-get install -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# Dépendances Python
COPY pcq/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Code applicatif
COPY pcq/ pcq/

# Configuration Streamlit (écoute sur 0.0.0.0)
COPY .streamlit/ /root/.streamlit/

# Volume pour la base de données persistante
VOLUME /app/pcq/data

# Port Streamlit
EXPOSE 8501

# Healthcheck
HEALTHCHECK --interval=60s --timeout=10s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8501/_stcore/health')" || exit 1
