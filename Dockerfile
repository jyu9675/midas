FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# copy only what the portal needs (see .dockerignore)
COPY server.py discover.py ingest.py datasets.tsv datasets_hydrated.tsv ./
COPY static ./static
EXPOSE 8080
# NOTE: AWS App Runner does not reliably honor this image CMD (it started the
# container with no command -> instant exit, no logs). On App Runner, set an
# explicit StartCommand in the service's ImageConfiguration (see scripts/aws/).
# -u = unbuffered stdout/stderr so logs stream to CloudWatch immediately.
CMD ["python", "-u", "-m", "uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8080"]
