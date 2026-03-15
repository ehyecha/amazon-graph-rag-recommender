from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.graphs import Neo4jGraph
from langchain_openai import ChatOpenAI

NEO4J_URI = "bolt://localhost:7687"     # 도커 네트워크 안이라면 서비스명 사용
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "airflow123"

# 1. DB 접속 및 무료 임베딩 모델 로드
graph = Neo4jGraph(url=NEO4J_URI, username=NEO4J_USER, password=NEO4J_PASSWORD)
embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")

def update_product_embeddings():
    # 2. 임베딩할 상품 데이터 가져오기
    # 제목(title)과 카테고리(category)를 합쳐서 풍부한 의미를 만듭니다.
    print("상품 데이터를 불러오는 중...")
    products = graph.query("""
        MATCH (p:Product) 
        RETURN id(p) AS node_id, p.title AS title, p.category AS category
    """)

    print(f"총 {len(products)}개의 상품을 처리합니다.")

    # 3. 루프를 돌며 벡터 생성 및 DB 저장
    for p in products:
        # 제목과 카테고리를 합친 문장 생성 (예: "로즈골드 스마트워치 Electronics, Smartwatches")
        content = f"{p['title']} {p['category']}"
        
        # 허깅페이스 모델로 벡터 생성 (384차원)
        vector = embeddings.embed_query(content)
        
        # DB에 벡터 속성(embedding) 추가
        # Neo4j 5.x 버전 이상에서는 리스트를 그대로 저장하면 벡터로 인식합니다.
        graph.query("""
            MATCH (p) WHERE id(p) = $node_id
            SET p.embedding = $vector
        """, {"node_id": p['node_id'], "vector": vector})
        
        print(f"업데이트 완료: {p['title']}")

    print("모든 상품의 벡터 업데이트가 완료되었습니다!")

# 실행
#update_product_embeddings()
def translate_to_english(question):
    prompt = f"Translate to English: {question}"
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    return llm.invoke(prompt).content
# 1. 사용자의 질문을 벡터로 변환 (무료 허깅페이스 모델 사용)
user_question = "블루투스 이어폰 추천해줘"
english_q = translate_to_english(user_question)
print("english q", english_q)
query_vector = embeddings.embed_query(english_q)

# 2. Neo4j 벡터 검색 쿼리 실행
# top_k: 가장 유사한 상품 몇 개를 가져올지 결정 (여기선 3개)
search_query = """
CALL db.index.vector.queryNodes('product_embeddings', 3, $vector)
YIELD node AS product, score
RETURN DISTINCT
    product.title AS title, 
    product.category AS category, 
    product.price AS price, 
    score
"""

results = graph.query(search_query, {"vector": query_vector})

# 3. 결과 출력
print(f"--- '{user_question}'에 대한 검색 결과 ---")
for res in results:
    print(f"[{round(res['score'] * 100, 1)}% 일치] {res['title']} ({res['price']}원)")