FROM python:3.11-slim

WORKDIR /app
COPY job.py ./

USER 10001:10001
CMD ["python", "-u", "job.py"]
