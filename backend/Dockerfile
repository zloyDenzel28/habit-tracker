FROM python:3.12-slim

# PYTHONPATH принципиален: pip install кладёт копию пакета в site-packages,
# а исходники мы монтируем в /app. Без явного пути контейнер может исполнять
# установленную копию, и правки перестанут применяться.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=UTC \
    PYTHONPATH=/app

WORKDIR /app

COPY pyproject.toml ./
COPY app ./app
RUN pip install --no-cache-dir .

COPY alembic.ini ./
COPY alembic ./alembic
