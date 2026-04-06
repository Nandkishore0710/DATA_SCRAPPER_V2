# Use the official Playwright Python image which includes all system dependencies
FROM mcr.microsoft.com/playwright/python:v1.48.0-noble

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Install only necessary extra system dependencies (Postgres driver)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Install Python dependencies
COPY extractor_platform/requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Browsers are already installed in this image, but we ensure chromium is ready
RUN playwright install chromium

# Copy project files
COPY extractor_platform /app/

# Expose port
EXPOSE 8000

# Default command
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "120", "core.wsgi:application"]
