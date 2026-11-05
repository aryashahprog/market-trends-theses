FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY signal_atlas ./signal_atlas
ENV SIGNAL_ATLAS_DATA_DIR=/data
VOLUME /data
EXPOSE 8080
CMD ["uvicorn", "signal_atlas.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080"]
