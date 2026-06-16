FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
  && apt-get install -y --no-install-recommends ffmpeg espeak-ng \
  && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-tts.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
  && pip install --no-cache-dir -r requirements-tts.txt

COPY . .
RUN chmod +x scripts/start_api.sh

EXPOSE 8000

CMD ["/app/scripts/start_api.sh"]
