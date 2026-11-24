FROM python:3.12-slim AS build
WORKDIR /w
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN useradd -m app && mkdir /data && chown app /data
COPY --from=build /install /usr/local
WORKDIR /srv
COPY app ./app
USER app
ENV DATABASE_URL=sqlite:////data/app.db
VOLUME /data
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
