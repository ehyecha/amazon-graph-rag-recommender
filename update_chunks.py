"""
청킹 기반 RAG 구현
- Product 텍스트를 청킹 후 Chunk 노드로 Neo4j에 저장
- Chunk별 임베딩 생성 및 벡터 인덱스 구축

구조:
(Product)──[:HAS_CHUNK]──▶ (Chunk {text, embedding, chunk_index})
"""
import re
from neo4j import GraphDatabase
from langchain_huggingface import HuggingFaceEmbeddings

NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "airflow123"

CHUNK_SIZE = 200      # 청크당 최대 단어 수
CHUNK_OVERLAP = 30    # 청크 간 겹치는 단어 수 (문맥 유지)
BATCH_SIZE = 50


def split_into_chunks(text: str, chunk_size: int, overlap: int) -> list[str]:
    """텍스트를 단어 단위로 청킹 (overlap으로 문맥 유지)"""
    if not text or not text.strip():
        return []

    words = text.split()
    if len(words) <= chunk_size:
        return [text.strip()]

    chunks = []
    start = 0
    while start < len(words):
        end = start + chunk_size
        chunk = " ".join(words[start:end])
        chunks.append(chunk.strip())
        if end >= len(words):
            break
        start += chunk_size - overlap

    return chunks


def create_chunk_index(driver):
    """chunk_embeddings 벡터 인덱스 생성"""
    with driver.session() as session:
        # 기존 인덱스 삭제
        try:
            session.run("DROP INDEX chunk_embeddings IF EXISTS")
        except Exception:
            pass
        # Neo4j 5.x 절차형 방식
        session.run("""
            CALL db.index.vector.createNodeIndex(
                'chunk_embeddings', 'Chunk', 'embedding', 384, 'cosine'
            )
        """)
    print("  chunk_embeddings 인덱스 생성 완료")


def delete_existing_chunks(driver):
    """기존 Chunk 노드 삭제"""
    with driver.session() as session:
        result = session.run("MATCH (c:Chunk) RETURN count(c) AS cnt").single()
        cnt = result["cnt"]
        if cnt > 0:
            print(f"  기존 Chunk {cnt:,}개 삭제 중...")
            session.run("MATCH (c:Chunk) DETACH DELETE c")
            print("  삭제 완료")


def build_chunks(driver, embeddings_model):
    """Product 텍스트를 청킹해서 Chunk 노드 생성 + 임베딩"""
    print("\nProduct 텍스트 로딩 중...")
    with driver.session() as session:
        products = session.run("""
            MATCH (p:Product)
            WHERE p.product_text IS NOT NULL AND p.product_text <> ''
            RETURN p.asin AS asin,
                   p.title AS title,
                   p.product_text AS product_text,
                   id(p) AS node_id
        """).data()

    total_products = len(products)
    print(f"  텍스트 있는 상품: {total_products:,}개")

    all_chunks = []
    for p in products:
        # title + product_text 합쳐서 청킹
        full_text = f"{p['title']}. {p['product_text']}"
        chunks = split_into_chunks(full_text, CHUNK_SIZE, CHUNK_OVERLAP)
        for idx, chunk_text in enumerate(chunks):
            all_chunks.append({
                "asin": p["asin"],
                "node_id": p["node_id"],
                "chunk_index": idx,
                "text": chunk_text,
            })

    total_chunks = len(all_chunks)
    avg_chunks = total_chunks / total_products if total_products else 0
    print(f"  생성된 청크: {total_chunks:,}개 (상품당 평균 {avg_chunks:.1f}개)")

    print("\n청크 임베딩 생성 및 Neo4j 저장 중...")
    with driver.session() as session:
        for i in range(0, total_chunks, BATCH_SIZE):
            batch = all_chunks[i:i + BATCH_SIZE]

            # 임베딩 생성
            texts = [c["text"] for c in batch]
            vectors = embeddings_model.embed_documents(texts)

            # Neo4j에 Chunk 노드 생성 + Product 연결
            session.run("""
                UNWIND $batch AS row
                MATCH (p:Product {asin: row.asin})
                CREATE (c:Chunk {
                    text: row.text,
                    chunk_index: row.chunk_index,
                    embedding: row.embedding,
                    asin: row.asin
                })
                CREATE (p)-[:HAS_CHUNK]->(c)
            """, batch=[
                {
                    "asin": batch[j]["asin"],
                    "text": batch[j]["text"],
                    "chunk_index": batch[j]["chunk_index"],
                    "embedding": vectors[j],
                }
                for j in range(len(batch))
            ])

            done = min(i + BATCH_SIZE, total_chunks)
            print(f"  [{done:,}/{total_chunks:,}] 완료", end="\r")

    print(f"\n  Chunk 노드 저장 완료!")
    return total_chunks


if __name__ == "__main__":
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    embeddings_model = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")

    print("=" * 50)
    print("청킹 기반 RAG 구축 시작")
    print(f"  청크 크기: {CHUNK_SIZE} 단어")
    print(f"  오버랩: {CHUNK_OVERLAP} 단어")
    print("=" * 50)

    # 기존 Chunk 삭제
    delete_existing_chunks(driver)

    # 벡터 인덱스 생성
    create_chunk_index(driver)

    # 청킹 + 임베딩 + 저장
    total = build_chunks(driver, embeddings_model)

    driver.close()
    print("\n✅ 완료!")
    print(f"   - Chunk 노드: {total:,}개 생성")
    print(f"   - chunk_embeddings 벡터 인덱스 구축")
    print(f"   - (Product)──[:HAS_CHUNK]──▶(Chunk) 관계 생성")
