FROM python:3.12-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg tesseract-ocr tesseract-ocr-fra && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=denoland/deno:bin /deno /usr/local/bin/deno

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ .
COPY entrypoint.sh /entrypoint.sh
# Servi par le bouton « Avoir MediaVior sur ton PC »
COPY PROMPT.md ./

# yt-dlp mis à jour au démarrage et dès qu'une nouvelle version sort (voir entrypoint.sh)
ENV LECOFFRE_AUTO_UPDATE=1

RUN mkdir -p /downloads

EXPOSE 8000

CMD ["sh", "/entrypoint.sh"]
