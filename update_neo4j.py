
from neo4j import GraphDatabase
import pandas as pd

# --- 설정 정보 ---
BOOTSTRAP_SERVERS = ['kafka:9092']  # 도커 네트워크 안이라면 서비스명 사용
TOPIC_NAME = 'amazon_electronics'
NEO4J_URI = "bolt://localhost:7687"     # 도커 네트워크 안이라면 서비스명 사용
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "airflow123"



def update_relationships(tx, asin, also_buy_list):
    query = """
    MATCH (p:Product {asin: $asin})
    
    // 1. 노드에 also_buy 리스트 속성 저장 (추가된 부분)
    SET p.also_buy = $also_buy_list
    
    // 2. 관계 생성 (기존 로직 유지)
    WITH p
    UNWIND $also_buy_list AS target_asin
    MATCH (p2:Product {asin: target_asin})
    MERGE (p)-[:ALSO_BOUGHT]->(p2)
    """
    tx.run(query, asin=asin, also_buy_list=also_buy_list)

# Neo4j 연결 설정
driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
# JSON 파일인 경우 (lines=True는 한 줄에 하나씩 JSON 객체가 있는 경우)
df = pd.read_json('./data/electronics_ontology_sample.json', lines=True)

# 필요한 컬럼(asin, also_buy)만 남겨서 가볍게 만들기
df = df[['asin', 'also_buy']]
with driver.session() as session:
    print("🚀 관계 업데이트 시작...")
    # 원본 데이터프레임(df) 순회
    for _, row in df.iterrows():
        asin = row['asin']
        also_buy = row.get('also_buy', []) # 데이터가 없으면 빈 리스트
        
        if also_buy:
            session.execute_write(update_relationships, asin, also_buy)
            
    print("✅ 모든 ALSO_BOUGHT 관계 업데이트 완료!")

driver.close()