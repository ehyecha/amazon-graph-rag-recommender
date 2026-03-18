# 🛍️ Amazon Electronics Graph-RAG 상품 추천 시스템

> Amazon Electronics 데이터를 기반으로 Graph-RAG 기술을 활용한 AI 상품 추천 챗봇 서비스

---

## 📌 프로젝트 개요

Amazon Electronics 30,000개 상품 데이터를 Airflow + Kafka 파이프라인으로 수집하고, Neo4j 지식그래프로 구축한 뒤 Graph-RAG 기반 LLM 추천 서비스를 구현한 프로젝트입니다.

한국어로 질문하면 자동으로 번역 후 벡터 유사도 검색을 통해 관련 상품을 추천해드립니다.

---

## 🏗️ 시스템 아키텍처

```
Amazon Electronics JSON 데이터 (30,000개)
            ↓
[Airflow] amazon_producer_dag
            ↓
Kafka Topic: amazon_electronics
            ↓
[Airflow] amazon_consumer_to_neo4j (병렬 워커 3개)
            ↓
Neo4j 지식그래프
(Product - Brand - Category - ALSO_BOUGHT)
            ↓
HuggingFace 임베딩 생성 (27,005개, 384차원)
            ↓
[LangGraph Agent]
한국어 질문 → 번역 → 벡터검색 → 한국어 답변
            ↓
Streamlit 챗봇 UI
```

---

## 📊 그래프 데이터 구조

```
Product ──[:ALSO_BOUGHT]──▶ Product
   │
   ├──[:MANUFACTURED_BY]──▶ Brand
   │
   └──[:BELONGS_TO]──▶ Category
```

- **노드**: Product (27,005개), Brand, Category
- **관계**: ALSO_BOUGHT (함께 구매), MANUFACTURED_BY (제조사), BELONGS_TO (카테고리)

---

## 🛠️ 기술 스택

| 분류 | 기술 |
|------|------|
| 파이프라인 | Airflow 2.7.1, Kafka (KRaft) |
| 그래프 DB | Neo4j 5.12 + Vector Index |
| 임베딩 | HuggingFace all-MiniLM-L6-v2 |
| LLM | GPT-4o-mini |
| Agent | LangGraph |
| UI | Streamlit |
| 인프라 | Docker, Docker Compose |

---

## ✨ 주요 기능

1. **한국어 질문 처리** - 한국어 질문을 자동으로 영어로 번역
2. **의미 기반 유사도 검색** - 벡터 임베딩으로 의미적으로 유사한 상품 탐색
3. **그래프 관계 활용** - ALSO_BOUGHT 관계로 함께 구매된 상품 연결
4. **예산/브랜드 필터링** - 자연어에서 예산, 브랜드 자동 추출 후 필터링
5. **LangGraph 워크플로우** - 분석 → 검색 → 답변 멀티노드 Agent 설계

---

## 🚀 실행 방법

### 1. 환경 설정
```bash
cp .env.example .env
# .env 파일에 OPENAI_API_KEY 입력
```

### 2. Docker 실행
```bash
docker-compose up -d
```

서비스 확인:
- Airflow: http://localhost:8080 (admin/admin)
- Neo4j: http://localhost:7474 (neo4j/airflow123)

### 3. Airflow DAG 실행
```
1) amazon_producer_dag 실행 → Kafka로 데이터 전송
2) amazon_consumer_to_neo4j 실행 → Neo4j에 적재
```

### 4. 그래프 관계 및 임베딩 생성
```bash
python update_neo4j.py       # ALSO_BOUGHT 관계 구축
python update_embedding.py   # 벡터 임베딩 생성
```

### 5. 서비스 실행
```bash
streamlit run app.py
# http://localhost:8501 접속
```

---

## 💬 사용 예시

```
👤 블루투스 이어폰 추천해줘
🤖 블루투스 이어폰 추천 상품입니다:
   1. Noise Cancelling Bluetooth Headphones - $2.00
   2. TRENDnet Bluetooth 4.0 USB 어댑터 - $12.99

👤 50달러 이하 스피커 있어?
🤖 50달러 이하 스피커 추천 상품입니다:
   1. JAM Classic Wireless Bluetooth Speaker - $16.99
```

---

## 📁 프로젝트 구조

```
amazon-project/
├── docker-compose.yml
├── dags/
│   ├── amazon_producer_v1.py     # Kafka Producer DAG
│   └── amazaon_consumer_v1.py    # Kafka Consumer → Neo4j DAG
├── data/
│   └── electronics_ontology_sample.json
├── update_neo4j.py               # ALSO_BOUGHT 관계 구축
├── update_embedding.py           # HuggingFace 임베딩 생성
├── main.py                       # LangGraph Agent
└── app.py                        # Streamlit UI
```

---

## ⚠️ 한계점 및 개선 방향

- 데이터 품질: 일부 상품의 가격 데이터에 HTML 코드 포함 → 정제 필요
- 임베딩 모델: 영어 특화 모델 사용으로 동의어 처리 한계 → 다국어 모델 교체 고려
- ALSO_BOUGHT 관계를 추천 로직에 직접 활용하는 Hybrid 검색 고도화 예정

## 성능 평가 (RAGAS)

RAG 시스템 품질을 정량적으로 평가하기 위해
RAGAS 프레임워크를 적용했습니다. (3회 평균)

| 지표 | 초기 | 개선 후 | 설명 |
|------|------|---------|------|
| Faithfulness | 0.50 | 0.77 | 검색 문서 기반 답변 충실도 |
| Answer Relevancy | nan | 0.60 | 질문 대비 답변 관련성 |

**개선 방법**
- 평가 LLM max_tokens 증가로 Faithfulness nan 문제 해결
- OpenAI 임베딩 추가로 Answer Relevancy 측정 가능

**추가 개선 방향**
- 한국어 번역 품질 개선으로 Answer Relevancy 향상 예정
- Reranking 적용으로 검색 품질 개선 예정