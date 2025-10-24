# Dockerfile
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    POETRY_VIRTUALENVS_CREATE=false

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl libpq-dev && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# If you use requirements.txt (default). Otherwise replace with Poetry section.
COPY requirements.txt /app/
RUN pip install --upgrade pip && pip install -r requirements.txt || true

# Code
COPY . /app/

# Gunicorn (Django) by default
ENV DJANGO_SETTINGS_MODULE=${DJANGO_SETTINGS_MODULE:-config.settings}
RUN useradd -r -u 999 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

CMD ["gunicorn", "config.wsgi:application", "--config", "/app/gunicorn.conf.py"]

ARG GIT_SHA=unknown
RUN echo "$GIT_SHA" > /app/.build_sha
