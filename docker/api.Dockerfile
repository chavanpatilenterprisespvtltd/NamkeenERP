# FILE PATH: docker/api.Dockerfile
# ─── API Image v1.1 (Session CS2 — image now contains web/, migrations/, config/, bootstrap/ and uses the entrypoint) ─
#
# [Session CS2] FIX — THE API IMAGE COPIED ONLY app/, SO UI PAGES 404'D AND MIGRATIONS/RELEASE MANIFEST WERE MISSING.
# Confirmed this session by reading this file (COPY ./app only) against app/__main__.py, which serves
# web/*.html via FileResponse and reads config/release_manifest.json at import time.
# THE FIX: copy web/, migrations/, config/ and bootstrap/; ENTRYPOINT docker/entrypoint.sh (env check +
# optional migrations). NOT touched: base image, pip install, non-root user, port.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY ./requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY ./app /app/app
COPY ./web /app/web
COPY ./migrations /app/migrations
COPY ./config /app/config
COPY ./bootstrap /app/bootstrap
COPY --chmod=0755 ./docker/entrypoint.sh /app/docker/entrypoint.sh
USER 10001:10001
EXPOSE 8000
ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["python", "-m", "app"]
