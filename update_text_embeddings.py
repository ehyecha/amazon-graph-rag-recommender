"""
Step 1: Neo4j Product 노드에 description + feature 텍스트 추가
Step 2: title + feature + description 합쳐서 임베딩 재생성
"""
import gzip
import json
from neo4j import GraphDatabase
from langchain_huggingface import HuggingFaceEmbeddings

NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "airflow123"
BATCH_SIZE = 100


def clean_text(value) -> str:
    """리스트 or 문자열을 깔끔한 텍스트로 변환"""
    if not value:
        return ""
    if isinstance(value, list):
        return " ".join(str(v).strip() for v in value if str(v).strip())
    return str(value).strip()


def truncate(text: str, max_chars: int = 500) -> str:
    """임베딩 모델 입력 길이 제한 (all-MiniLM-L6-v2: ~256 토큰)"""
    return text[:max_chars] if len(text) > max_chars else text


# ===== Step 1: 원본 데이터에서 텍스트 추출 =====

def load_text_from_raw(neo4j_asins: set) -> dict:
    """원본 JSON에서 Neo4j에 있는 asin의 description + feature 추출"""
    print("원본 데이터에서 텍스트 추출 중...")
    asin_text = {}
    seen = set()

    with gzip.open("./data/meta_Electronics.json.gz", "rt") as f:
        for line in f:
            item = json.loads(line)
            asin = item.get("asin")
            if not asin or asin not in neo4j_asins or asin in seen:
                continue
            seen.add(asin)

            desc = clean_text(item.get("description", []))
            feat = clean_text(item.get("feature", []))
            text = truncate(f"{feat} {desc}".strip())

            if text:
                asin_text[asin] = text

            if len(seen) >= len(neo4j_asins):
                break

    print(f"  텍스트 추출 완료: {len(asin_text):,}개 / {len(neo4j_asins):,}개")
    return asin_text


# ===== Step 2: Neo4j 업데이트 =====

def update_text_in_neo4j(driver, asin_text: dict):
    """Neo4j Product 노드에 product_text 속성 저장"""
    print("\nNeo4j에 텍스트 저장 중...")
    items = list(asin_text.items())
    total = len(items)

    with driver.session() as session:
        for i in range(0, total, BATCH_SIZE):
            batch = [{"asin": a, "text": t} for a, t in items[i:i+BATCH_SIZE]]
            session.run("""
                UNWIND $batch AS row
                MATCH (p:Product {asin: row.asin})
                SET p.product_text = row.text
            """, batch=batch)

            done = min(i + BATCH_SIZE, total)
            print(f"  [{done:,}/{total:,}] 저장 완료", end="\r")

    print(f"\n  텍스트 저장 완료!")


# ===== Step 3: 임베딩 재생성 =====

def update_embeddings(driver, embeddings_model):
    """title + product_text 합쳐서 임베딩 재생성"""
    print("\n임베딩 재생성 중...")

    with driver.session() as session:
        # 텍스트가 있는 상품 우선, 없는 상품도 처리
        products = session.run("""
            MATCH (p:Product)
            RETURN p.asin AS asin,
                   p.title AS title,
                   coalesce(p.product_text, '') AS product_text,
                   id(p) AS node_id
        """).data()

    total = len(products)
    print(f"  총 {total:,}개 상품 임베딩 재생성")

    with driver.session() as session:
        for i in range(0, total, BATCH_SIZE):
            batch_products = products[i:i+BATCH_SIZE]
            batch_vectors = []

            for p in batch_products:
                # title + product_text 결합
                content = f"{p['title']} {p['product_text']}".strip()
                vector = embeddings_model.embed_documents([content])[0]
                batch_vectors.append({
                    "node_id": p["node_id"],
                    "vector": vector
                })

            session.run("""
                UNWIND $batch AS row
                MATCH (p) WHERE id(p) = row.node_id
                SET p.embedding = row.vector
            """, batch=batch_vectors)

            done = min(i + BATCH_SIZE, total)
            print(f"  [{done:,}/{total:,}] 임베딩 완료", end="\r")

    print(f"\n  임베딩 재생성 완료!")


# ===== 실행 =====

if __name__ == "__main__":
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    embeddings_model = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")

    # Neo4j의 전체 asin 목록 가져오기
    print("Neo4j asin 목록 로딩 중...")
    with driver.session() as session:
        neo4j_asins = {r["asin"] for r in session.run(
            "MATCH (p:Product) WHERE p.asin IS NOT NULL RETURN p.asin AS asin"
        )}
    print(f"  Neo4j 상품 수: {len(neo4j_asins):,}개")

    # Step 1: 원본 데이터에서 텍스트 추출
    asin_text = load_text_from_raw(neo4j_asins)

    # Step 2: Neo4j에 텍스트 저장
    update_text_in_neo4j(driver, asin_text)

    # Step 3: 임베딩 재생성
    update_embeddings(driver, embeddings_model)

    driver.close()
    print("\n✅ 모든 작업 완료!")
    print("   - product_text 속성 추가됨")
    print("   - embedding 재생성 완료 (title + feature + description 기반)")
