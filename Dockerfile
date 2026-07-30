FROM python:3.12-slim

WORKDIR /app

# 安装 Python 依赖（仅核心包，不含大模型依赖）
COPY requirements-deploy.txt requirements.txt
RUN pip install --no-cache-dir -r requirements-deploy.txt

# 复制项目
COPY . .

EXPOSE 8001

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "2"]
