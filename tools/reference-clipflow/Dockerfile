FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 HF_HOME=/opt/asr-cache CLIPFLOW_ASR_MODEL_CACHE=/opt/asr-cache
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY . /app
RUN python -m pip install --no-cache-dir '.[cloud-server]' \
 && python -c "from faster_whisper import WhisperModel; WhisperModel('small', device='cpu',compute_type='int8',download_root='/opt/asr-cache')"
RUN useradd --system --uid 10001 app && chown -R app:app /opt/asr-cache /app
USER app
EXPOSE 8000
CMD ["sh","-c","uvicorn clipflow.cloud_server:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --no-access-log"]
