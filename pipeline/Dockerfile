FROM python:3.11-slim

WORKDIR /app

# Install the required library
RUN pip install --no-cache-dir prometheus_client

# We'll run the build context from the project root so we can copy the script
COPY mock_pipeline.py /app/

# Use -u to ensure Python output is unbuffered and shows up in Docker logs instantly
CMD ["python", "-u", "mock_pipeline.py"]
