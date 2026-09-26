# FILE PATH: docker/worker.Dockerfile
# ─── Worker Image v1.1 (Session CS2 — same content as API image; uses the entrypoint) ─
#
# [Session CS2] FIX — WORKER IMAGE LACKED config/ AND migrations/ AND BYPASSED docker/entrypoint.sh.
# THE FIX: same COPY set as docker/api.Dockerfile and ENTRYPOINT docker/entrypoint.sh. The worker
# itself (app/worker.py) now processes the notification outbox — see that file's header.
# NOT touched: base image, non-root user.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY ./requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY ./app /app/app
COPY ./web /app/web
COPY ./migrations /app/migrations
COPY ./config /app/config
COPY --chmod=0755 ./docker/entrypoint.sh /app/docker/entrypoint.sh
USER 10001:10001
ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["python", "-m", "app.worker"]
