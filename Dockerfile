FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Shanghai \
    APP_HOME=/app

WORKDIR $APP_HOME

# 容器默认 UTC，而业务按北京时间。tzdata 不装的话 ZoneInfo('Asia/Shanghai') 会抛异常。
RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata \
 && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip config set global.index-url https://mirrors.cloud.tencent.com/pypi/simple \
 && pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 80
# 端口要和云托管控制台「服务设置 → 端口」填的一致
CMD exec gunicorn --bind :80 --workers 2 --threads 4 --timeout 30 \
      --access-logfile - --error-logfile - wsgi:app
