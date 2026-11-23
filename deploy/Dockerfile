FROM python:3.12-slim
RUN pip install --no-cache-dir tzdata
WORKDIR /app
COPY app/ /app/
ENV ANCORAS_DB=/data/kaizen.db ANCORAS_TZ=America/Sao_Paulo
VOLUME /data
EXPOSE 8787
CMD ["python3", "app.py", "serve", "--host", "0.0.0.0", "--port", "8787"]
