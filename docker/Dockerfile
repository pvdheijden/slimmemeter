# One image for the P1-data client and the weather client, see compose.yaml.
# Build from the repository root: docker build -f docker/Dockerfile .
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

# Only the service code, the tests stay out of the image
COPY p1dataclient/p1dataclient.py p1dataclient/p1datametrics.py p1dataclient/p1telegram.py p1dataclient/
COPY weather/weather.py weather/buienradar.py weather/

# The scripts import their modules directly, so each runs from its own directory (compose.yaml)
USER nobody
