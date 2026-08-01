"""
JSON snake_case → camelCase 转换中间件
通过 @app.middleware("http") 注册
"""
import json
from typing import Any
from starlette.responses import Response


def snake_to_camel(name: str) -> str:
    if "_" not in name:
        return name
    parts = name.split("_")
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


def convert_keys(data: Any) -> Any:
    if isinstance(data, dict):
        return {snake_to_camel(k): convert_keys(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [convert_keys(item) for item in data]
    return data


async def camelcase_middleware(request, call_next):
    """将 JSON 响应的 snake_case 键转为 camelCase"""
    response = await call_next(request)
    
    ct = response.headers.get("content-type", "")
    if "application/json" not in ct:
        return response

    try:
        body = response.body
    except (RuntimeError, AttributeError):
        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk)
        body = b"".join(chunks)

    if not body:
        return response

    try:
        data = json.loads(body)
        converted = convert_keys(data)
        new_body = json.dumps(converted, ensure_ascii=False).encode("utf-8")
        status_code = response.status_code
        if status_code < 400 and isinstance(data, dict):
            code = data.get("code")
            if isinstance(code, int) and code >= 400:
                status_code = code
        
        # 构建新响应，去掉旧的 Content-Length（新版 body 长度不同）
        headers = dict(response.headers)
        headers.pop("content-length", None)
        return Response(
            content=new_body,
            status_code=status_code,
            headers=headers,
            media_type=response.media_type,
        )
    except Exception:
        return Response(
            content=body,
            status_code=response.status_code,
            headers=dict(response.headers),
            media_type=response.media_type,
        )
