# edu-ai-platform

智慧教育管理系统 — Python + AI 重构版

## 技术栈

- **后端：** FastAPI + SQLAlchemy 2.0 + Alembic
- **数据库：** MySQL 8.0（沿用原 student_db）
- **缓存：** Redis
- **AI：** LangChain + LangGraph + ChromaDB
- **认证：** JWT（兼容原前端 Token）
- **前端：** 原 HTML + Bootstrap 5（仅接口适配）

## 快速启动

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env 填入数据库密码和 API Key

# 3. 启动（注意清除 PYTHONPATH 避免冲突）
PYTHONPATH="" .venv/Scripts/python run.py

# 或者直接：uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

> ⚠️ 如果使用 `uvicorn` 命令启动，需要先清除 PYTHONPATH 环境变量：  
> Windows PowerShell: `$env:PYTHONPATH=""`  
> Git Bash: `PYTHONPATH="" uvicorn app.main:app --reload`

## 项目结构

```
edu-ai-platform/
├── app/           # FastAPI 应用
│   ├── main.py       # 入口
│   ├── config.py     # 配置
│   ├── database.py   # 数据库连接
│   ├── models/       # SQLAlchemy 模型
│   ├── schemas/      # Pydantic 序列化
│   ├── routers/      # API 路由
│   ├── services/     # 业务逻辑
│   ├── middleware/   # 中间件
│   └── utils/        # 工具函数
├── ai/            # AI 功能模块
├── static/        # 前端静态文件
└── scripts/       # 工具脚本
```
