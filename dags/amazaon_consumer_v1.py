import json
from kafka import KafkaConsumer
from airflow.operators.python import PythonOperator
from neo4j import GraphDatabase
from airflow import DAG
from datetime import timedelta, datetime

# --- 설정 정보 ---
BOOTSTRAP_SERVERS = ['kafka:9092']  # 도커 네트워크 안이라면 서비스명 사용
TOPIC_NAME = 'amazon_electronics'
NEO4J_URI = "bolt://neo4j:7687"     # 도커 네트워크 안이라면 서비스명 사용
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "airflow123"

# --- 실제 실행될 로직 ---
def kafka_to_neo4j_worker(worker_id):
    """Kafka에서 읽어서 Neo4j에 저장하는 메인 로직"""
    print(f"🚀 Worker {worker_id} 시작")
    
    # 1. 컨슈머 설정 (각 태스크마다 독립적인 컨슈머 생성)
    consumer = KafkaConsumer(
        TOPIC_NAME,
        bootstrap_servers=BOOTSTRAP_SERVERS,
        auto_offset_reset='earliest',
        group_id='neo4j-loader-group-v2', # 동일한 group_id로 병렬 처리
        value_deserializer=lambda x: json.loads(x.decode('utf-8')),
        # 데이터가 없으면 10초 후 종료 (Airflow 태스크 완료를 위해)
        consumer_timeout_ms=10000 
    )

    # 2. Neo4j 드라이버 설정
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    
    count = 0
    filtered_count = 0

    try:
        with driver.session() as session:
            for message in consumer:
                data = message.value
                #categories = data.get('category', [])

                # Electronics 필터링
                #if any('Electronics' in cat for cat in categories):
                #if categories and str(categories[0]).strip().lower() == 'electronics':
                #if categories and any('electronics' in str(cat).lower() for cat in categories):
                session.execute_write(_merge_node, data)
                filtered_count += 1
                
                count += 1
                if count % 1000 == 0:
                    print(f"👷 Worker {worker_id} | 확인: {count} | 저장: {filtered_count}")
                    
    finally:
        driver.close()
        consumer.close()
        print(f"🏁 Worker {worker_id} 종료 (총 {filtered_count}개 저장)")

def _merge_node(tx, data):
    query = """
    MERGE (p:Product {asin: $asin})
    SET p.title = $title,
        p.price = $price,
        p.brand = $brand,
        p.categories = $categories
    """
    tx.run(query, 
           asin=data.get('asin'), 
           title=data.get('title'),
           price=data.get('price'),
           brand=data.get('brand'),
           categories=data.get('category'))

# --- DAG 정의 ---
default_args = {
    'owner': 'airflow',
    'start_date': datetime(2026, 1, 1),
    'retries': 1
}

with DAG(
    'amazon_consumer_to_neo4j',
    default_args=default_args,
    schedule_interval='@once',
    catchup=False,
    dagrun_timeout=timedelta(hours=10)
) as dag:

    # 3개의 병렬 워커 생성
    for i in range(3):
        PythonOperator(
            task_id=f'consumer_worker_{i}',
            python_callable=kafka_to_neo4j_worker,
            op_args=[i] # worker_id 전달
        )