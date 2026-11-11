FROM python:3.12-alpine

LABEL maintainer="yjj3019 <yjj3019@users.noreply.github.com>"
LABEL description="Pickle Telegram Connector & Low-Latency Watcher"

WORKDIR /app

COPY pyproject.toml /app/
COPY pickle_tg/ /app/pickle_tg/
COPY bin/ /app/bin/

ENV PYTHONUNBUFFERED=1
ENV PATH="/app/bin:${PATH}"

CMD ["pickle-tg", "daemon"]
