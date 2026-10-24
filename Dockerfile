FROM python:3.12-slim

WORKDIR /app

# postgresql-client liefert pg_dump / psql für die Backup-Funktion, tzdata die Zeitzonen (TZ)
RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ .
COPY CHANGELOG.md .

RUN mkdir -p /data/backups

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
