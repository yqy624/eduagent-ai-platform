FROM python:3.12-slim

WORKDIR /app

# 安装 Python 依赖（使用国内镜像加速）
COPY requirements-deploy.txt /app/requirements.txt
RUN pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/ && \
    pip install --no-cache-dir -r /app/requirements.txt

# 复制项目
COPY . .

EXPOSE 8001

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "2"]
