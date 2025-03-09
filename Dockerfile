FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY *.py .
COPY templates/ templates/

# Create directories for volumes
RUN mkdir -p /app/config /data/db

# Set default config if none exists
COPY aurora_config.json /app/config/

# Set volumes for persistent storage
VOLUME /app/config
VOLUME /data/db

# Set environment variables
ENV DB_PATH=/data/db/aurora_data.db
ENV CONFIG_FILE=/app/config/aurora_config.json
ENV INVERTER_HOST=192.168.1.100
ENV INVERTER_PORT=8899
ENV WEB_HOST=0.0.0.0
ENV WEB_PORT=5000
ENV POLLING_INTERVAL=300

# Expose web port
EXPOSE 5000

# Run the application
CMD ["python", "aurora_web_app.py"]