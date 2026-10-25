FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8080
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt && useradd --create-home --uid 10001 forward
COPY --chown=forward:forward backend.py import_snapshot.py schema_postgres.sql ./
COPY --chown=forward:forward data/forward-snapshot.json ./data/forward-snapshot.json
# This image runs the read-only API. Configure DATABASE_URL for a separately
# imported PostgreSQL snapshot, or mount an owned SQLite database at /data.
ENV BAKKEN_DB_PATH=/data/forward.sqlite3
USER forward
EXPOSE 8080
CMD ["sh", "-c", "exec gunicorn --bind \"0.0.0.0:${PORT:-8080}\" --workers 2 --threads 4 --timeout 30 --access-logfile - backend:application"]
