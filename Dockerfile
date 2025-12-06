# Python 3.11 with FreeTDS ODBC for SQL Server connectivity
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies including FreeTDS ODBC driver
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    curl \
    libpq-dev \
    postgresql-client \
    unixodbc \
    unixodbc-dev \
    freetds-dev \
    freetds-bin \
    tdsodbc \
    && rm -rf /var/lib/apt/lists/*

# Configure FreeTDS ODBC driver (auto-detect architecture)
RUN ARCH=$(dpkg --print-architecture) && \
    if [ "$ARCH" = "arm64" ]; then ARCH="aarch64"; fi && \
    ODBC_PATH=$(find /usr/lib -name "libtdsodbc.so" 2>/dev/null | head -1 | sed 's|/libtdsodbc.so||') && \
    echo "[FreeTDS]\n\
Description = FreeTDS Driver\n\
Driver = ${ODBC_PATH}/libtdsodbc.so\n\
Setup = ${ODBC_PATH}/libtdsS.so\n\
UsageCount = 1\n\
" > /etc/odbcinst.ini

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy FreeTDS configuration
COPY freetds.conf /etc/freetds/freetds.conf

# Copy application code
COPY . .

# Set environment variables
ENV FLASK_APP=app.main:app
ENV FLASK_ENV=development
ENV PYTHONUNBUFFERED=1

# Expose port
EXPOSE 5557

# Run Flask app
CMD ["python", "-m", "flask", "run", "--host=0.0.0.0", "--port=5557"]
