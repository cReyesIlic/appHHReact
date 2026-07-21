FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Mantenemos la misma estructura que el host (project_root = parents[3] desde app/core/config.py)
WORKDIR /srv/app_principal/backend

# System deps para PyPDF2, reportlab, pandas
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    libxml2-dev libxslt-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install -r requirements.txt \
    && pip install numpy

COPY app ./app
COPY scripts ./scripts
RUN mkdir -p /srv/app_principal/database /srv/app_principal/storage
# Skills (playbooks markdown) viajan con la imagen
# (Ya están dentro de app/skills/)

EXPOSE 8010

# Database y storage se montan como volumes desde docker-compose en /srv/app_principal/{database,storage}
ENV DATABASE_DIR="database/proyectos 9.db"

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8010"]
