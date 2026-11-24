# syntax=docker/dockerfile:1.7
# Build context: repository root (needs eval/ and scripts/ for seeding and the synthetic data generator).
FROM python:3.12-slim AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
COPY services/core-api/pyproject.toml .
RUN python -c "import tomllib,pathlib;pathlib.Path('req.txt').write_text(chr(10).join(tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']))" \
 && python -m venv /venv && /venv/bin/pip install --upgrade pip && /venv/bin/pip install -r req.txt

FROM python:3.12-slim AS runtime
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr libpq5 \
 && rm -rf /var/lib/apt/lists/* && useradd -r -u 10001 -m nsip
ENV PATH=/venv/bin:$PATH PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
COPY --from=build /venv /venv
WORKDIR /srv/services/core-api
COPY services/core-api/ /srv/services/core-api/
COPY services/auth-service/app/seed.py /srv/services/auth-service/app/seed.py
COPY services/mock-gateway/ /srv/services/mock-gateway/
COPY eval/ /srv/eval/
COPY scripts/ /srv/scripts/
RUN mkdir -p /srv/services/core-api/var && chown -R nsip /srv/services/core-api/var
USER 10001
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/health')"
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*' --workers ${WEB_CONCURRENCY:-2}"]
