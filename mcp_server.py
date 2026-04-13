from mcp.server.fastmcp import FastMCP
from langchain_neo4j import Neo4jGraph
from langchain_openai import ChatOpenAI

# ===== 즉시 초기화 (가벼운 것만) =====
graph = Neo4jGraph(url="bolt://localhost:7687", username="neo4j", password="airflow123")
llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

mcp = FastMCP("Amazon Graph-RAG 추천 시스템")

# ===== 지연 로딩: HuggingFace 모델은 첫 호출 시 로드 =====
_embeddings = None

def get_embeddings():
    global _embeddings
    if _embeddings is None:
        from langchain_huggingface import HuggingFaceEmbeddings
        _embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
    return _embeddings


# ===== MCP 툴 정의 =====

@mcp.tool()
def graph_search(category: str = "", brand: str = "", budget: int = 0) -> str:
    """
    Neo4j 그래프 DB에서 카테고리/브랜드/예산으로 아마존 상품을 검색합니다.
    브랜드나 카테고리가 명확할 때 사용하세요.
    예: category="Headphones", brand="Samsung", budget=50
    """
    conditions = []
    params = {}

    if category:
        params["category"] = category
        conditions.append("category IS NOT NULL AND toLower(category.name) CONTAINS toLower($category)")
    if brand:
        params["brand"] = brand
        conditions.append("brand IS NOT NULL AND toLower(brand.name) CONTAINS toLower($brand)")
    if budget > 0:
        params["budget"] = budget
        conditions.append("toFloat(replace(replace(split(product.price, ' - ')[0], '$', ''), ',', '')) <= $budget")

    where_clause = " AND ".join(conditions) if conditions else "true"

    query = f"""
    MATCH (product:Product)
    OPTIONAL MATCH (product)-[:MANUFACTURED_BY]->(brand:Brand)
    OPTIONAL MATCH (product)-[:BELONGS_TO]->(category:Category)
    WITH product, brand, category
    WHERE {where_clause}
    OPTIONAL MATCH (product)-[:ALSO_BOUGHT]->(related:Product)
    RETURN DISTINCT
        product.title AS title,
        product.price AS price,
        brand.name AS brand,
        MIN(category.name) AS category,
        collect(DISTINCT related.title)[0..3] AS also_bought
    LIMIT 5
    """

    results = graph.query(query, params)
    if not results:
        return "검색 결과가 없습니다. 다른 조건으로 시도해보세요."
    return str(results)


@mcp.tool()
def vector_search(query: str, category: str = "", budget: int = 0) -> str:
    """
    벡터 유사도로 아마존 상품을 검색합니다.
    모호한 키워드나 자연어 질문에 적합합니다.
    예: query="wireless earbuds for running", category="Headphones", budget=100
    """
    # 한국어 → 영어 번역 + 동의어 확장
    try:
        english_query = llm.invoke(f"""
            Translate to English and expand with synonyms: {query}
            예시: "블루투스 이어폰" → "bluetooth earphone earbuds wireless headphone"
            결과는 단어들만 나열해줘.
        """).content.strip() or query
    except Exception:
        english_query = query

    query_vector = get_embeddings().embed_query(english_query)

    conditions = ["score > 0.60"]
    params = {"vector": query_vector}

    if category:
        params["category"] = category
        conditions.append("category IS NOT NULL AND toLower(category.name) CONTAINS toLower($category)")
    if budget > 0:
        params["budget"] = budget
        conditions.append("toFloat(replace(replace(split(product.price, ' - ')[0], '$', ''), ',', '')) <= $budget")

    where_clause = " AND ".join(conditions)

    cypher = f"""
    CALL db.index.vector.queryNodes('chunk_embeddings', 50, $vector)
    YIELD node AS chunk, score
    MATCH (product:Product)-[:HAS_CHUNK]->(chunk)
    OPTIONAL MATCH (product)-[:MANUFACTURED_BY]->(brand:Brand)
    OPTIONAL MATCH (product)-[:BELONGS_TO]->(category:Category)
    WITH product, chunk, score, brand, category
    WHERE {where_clause}
    OPTIONAL MATCH (product)-[:ALSO_BOUGHT]->(related:Product)
    RETURN DISTINCT
        product.title AS title,
        product.price AS price,
        brand.name AS brand,
        MIN(category.name) AS category,
        chunk.text AS chunk_text,
        collect(DISTINCT related.title)[0..3] AS also_bought,
        score
    ORDER BY score DESC LIMIT 5
    """

    results = graph.query(cypher, params)
    if not results:
        return "검색 결과가 없습니다. 다른 키워드로 시도해보세요."
    return str(results)


@mcp.tool()
def get_also_bought(product_title: str) -> str:
    """
    특정 상품을 구매한 고객이 함께 구매한 상품 목록을 가져옵니다.
    예: product_title="Bluetooth Speaker"
    """
    results = graph.query("""
        MATCH (p:Product)
        WHERE toLower(p.title) CONTAINS toLower($title)
        OPTIONAL MATCH (p)-[:ALSO_BOUGHT]->(related:Product)
        RETURN p.title AS product,
               collect(DISTINCT related.title)[0..5] AS also_bought
        LIMIT 1
    """, {"title": product_title})

    if not results or not results[0].get("also_bought"):
        return "함께 구매한 상품 정보가 없습니다."
    return str(results)


if __name__ == "__main__":
    mcp.run()
