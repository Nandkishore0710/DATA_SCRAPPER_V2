# Use the official Playwright Python image which includes all system dependencies
FROM mcr.microsoft.com/playwright/python:v1.48.0-noble

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV PYTHONPATH=/app

# Install only necessary extra system dependencies (Postgres driver)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    build-essential \
    netcat-traditional \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Install Python dependencies
COPY extractor_platform/requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Browsers are already installed in this image
RUN playwright install chromium

# Copy project files
COPY extractor_platform /app/

# Expose port
EXPOSE 8000

# Default command: Wait for DB, migrate, then start Gunicorn
CMD sh -c "python manage.py migrate && python manage.py collectstatic --no-input && gunicorn --bind 0.0.0.0:8000 --workers 3 --timeout 120 --chdir /app core.wsgi:application"
