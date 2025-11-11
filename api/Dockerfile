FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt \
    && pip install --no-cache-dir gunicorn

# app.py + templates are bind-mounted by compose; keep empty dirs for build
RUN mkdir -p /app/templates

ENV DB_PATH=/data/commute.db
EXPOSE 5000
CMD ["gunicorn","-w","2","-b","0.0.0.0:5000","app:app"]
