#!/usr/bin/env python
"""
课程文档索引脚本 — 将课程资料文件解析、切片、写入向量库
用法: .venv/Scripts/python scripts/ingest_course_docs.py
"""
import sys
import os

# 修复 sys.path — 优先使用项目 .venv
_proj = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_venv_sp = os.path.join(_proj, ".venv", "Lib", "site-packages")
for p in list(sys.path):
    if _venv_sp in p: sys.path.remove(p)
sys.path.insert(0, _venv_sp)
if _proj in sys.path: sys.path.remove(_proj)
sys.path.insert(1, _proj)

import asyncio
from datetime import datetime
from sqlalchemy import select

from app.database import async_session_factory
from app.models.models import Course, StoredFile
from app.models.ai_models import AiDocumentChunk, AiIndexJob
from ai.rag.loader import DocumentLoader, TextSplitter
from ai.rag.vector_store import VectorStoreManager


async def ingest_all():
    """索引所有课程文件"""
    print("=" * 50)
    print("📚 课程文档索引工具")
    print("=" * 50)

    async with async_session_factory() as db:
        # 获取所有课程
        result = await db.execute(select(Course))
        courses = list(result.scalars().all())
        print(f"\n找到 {len(courses)} 门课程")

        loader = DocumentLoader()
        splitter = TextSplitter(chunk_size=500, chunk_overlap=50)
        vs = VectorStoreManager()

        total_chunks = 0

        for course in courses:
            print(f"\n📖 课程: {course.name} (ID={course.id})")
            
            # 获取该课程已上传的文件
            files_result = await db.execute(
                select(StoredFile).where(StoredFile.course_id == course.id)
            )
            files = list(files_result.scalars().all())

            if not files:
                print(f"  ⚠️ 没有上传的课程资料")
                # 创建一个示例文档
                sample_content = f"""
# {course.name} 课程大纲

## 课程简介
{course.description or '本课程旨在帮助学生掌握核心知识和技能。'}

## 教学目标
1. 理解课程核心概念和基本原理
2. 掌握实际操作和问题解决能力
3. 培养批判性思维和创新能力

## 教学内容安排
1. 第一周：课程导论与基础知识
2. 第二周：核心概念讲解
3. 第三周：实践操作与案例分析
4. 第四周：综合项目与考核

## 考核方式
- 平时作业：30%
- 期中考试：30%
- 期末考试：40%

## 参考教材
1. 《{course.name}》- 主教材
2. 课程讲义与课件
3. 在线资源与学术论文
"""
                chunks = splitter.split_text(sample_content)
                doc_chunks = []
                for i, chunk in enumerate(chunks):
                    doc_chunks.append({
                        "course_id": course.id,
                        "chunk_index": i,
                        "content": chunk,
                        "content_hash": vs.compute_content_hash(chunk),
                        "source": f"课程大纲_{course.name}",
                        "source_type": "sample",
                        "char_count": len(chunk),
                    })

                # 保存到数据库
                for dc in doc_chunks:
                    chunk_record = AiDocumentChunk(
                        course_id=dc["course_id"],
                        chunk_index=dc["chunk_index"],
                        content_hash=dc["content_hash"],
                        source=dc["source"],
                        source_type=dc["source_type"],
                        char_count=dc["char_count"],
                        created_at=datetime.now(),
                    )
                    db.add(chunk_record)

                await db.flush()

                # 索引到向量库
                from langchain_core.documents import Document
                docs = [
                    Document(
                        page_content=dc["content"],
                        metadata={"course_id": course.id, "source": dc["source"], "chunk_index": dc["chunk_index"]}
                    )
                    for dc in doc_chunks
                ]
                count = vs.add_documents(docs, collection_name=f"course_{course.id}")
                total_chunks += count
                print(f"  ✅ 创建 {len(doc_chunks)} 个示例文档切片并索引")
                continue

            # 处理已有文件
            for file in files:
                file_path = os.path.join(
                    os.path.dirname(os.path.dirname(__file__)),
                    file.storage_path
                )
                if not os.path.exists(file_path):
                    print(f"  ⚠️ 文件不存在: {file.storage_path}")
                    continue

                # 创建索引任务
                job = AiIndexJob(
                    file_id=file.id, course_id=course.id,
                    status="RUNNING", created_at=datetime.now(),
                )
                db.add(job)
                await db.flush()

                try:
                    text = loader.load(file_path)
                    if not text:
                        print(f"  ⚠️ 无法解析: {file.original_name}")
                        job.status = "FAILED"
                        job.error_message = "无法解析文件格式"
                        continue

                    chunks = splitter.split_text(text)
                    doc_chunks = []
                    for i, chunk in enumerate(chunks):
                        doc_chunks.append({
                            "course_id": course.id,
                            "file_id": file.id,
                            "chunk_index": i,
                            "content": chunk,
                            "content_hash": vs.compute_content_hash(chunk),
                            "source": file.original_name,
                            "source_type": file.extension or "unknown",
                            "char_count": len(chunk),
                        })

                    from langchain_core.documents import Document
                    docs = [
                        Document(
                            page_content=dc["content"],
                            metadata={
                                "course_id": course.id,
                                "file_id": file.id,
                                "source": dc["source"],
                                "chunk_index": dc["chunk_index"],
                            }
                        )
                        for dc in doc_chunks
                    ]
                    count = vs.add_documents(docs, collection_name=f"course_{course.id}")

                    # 保存到 DB
                    for dc in doc_chunks:
                        chunk_record = AiDocumentChunk(
                            course_id=dc["course_id"],
                            file_id=dc["file_id"],
                            chunk_index=dc["chunk_index"],
                            content_hash=dc["content_hash"],
                            source=dc["source"],
                            source_type=dc["source_type"],
                            char_count=dc["char_count"],
                            created_at=datetime.now(),
                        )
                        db.add(chunk_record)

                    job.status = "COMPLETED"
                    job.total_chunks = len(doc_chunks)
                    job.finished_at = datetime.now()
                    total_chunks += count
                    print(f"  ✅ {file.original_name}: {len(doc_chunks)} 个切片 → 向量库")

                except Exception as e:
                    job.status = "FAILED"
                    job.error_message = str(e)
                    print(f"  ❌ {file.original_name}: 失败 - {e}")
                
                await db.flush()

        await db.commit()
        
        print(f"\n{'=' * 50}")
        print(f"✅ 索引完成！共 {total_chunks} 个文档切片写入向量库")
        print(f"📁 向量库位置: {vs.persist_directory}")


if __name__ == "__main__":
    asyncio.run(ingest_all())
