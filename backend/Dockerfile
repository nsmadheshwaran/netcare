FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# /app/storage exists in the image so the mounted volume inherits netcare ownership.
RUN useradd --create-home netcare && mkdir -p /app/storage && chown -R netcare /app
USER netcare
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:8000/ready')"
# Apply migrations, then serve. Single worker keeps the in-memory login limiter accurate.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'"]
