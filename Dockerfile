FROM python:3.12-slim

WORKDIR /app

# 安装 Python 依赖（纯 wheel，无需编译 C 扩展）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制项目
COPY . .

EXPOSE 8001

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "2"]
