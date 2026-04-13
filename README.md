# 🛍️ Amazon Electronics Graph-RAG 상품 추천 멀티에이전트 시스템

> Amazon Electronics 30,000개 상품 데이터를 기반으로 Graph-RAG와 멀티에이전트 아키텍처를 결합한 AI 쇼핑 어시스턴트

---

## 📌 프로젝트 개요

Amazon Electronics 데이터를 Airflow + Kafka 파이프라인으로 수집하고, Neo4j 지식그래프로 구축한 뒤 LangGraph Supervisor 패턴 기반 멀티에이전트로 상품 검색/비교/추천 서비스를 구현한 프로젝트입니다.

Streamlit UI와 Claude Desktop MCP 연동 두 가지 방식으로 서비스를 노출하며, RAGAS로 검색 성능을 정량 평가했습니다.

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
┌─────────────────────────────────────────┐
│         LangGraph 멀티에이전트           │
│                                         │
│  사용자 질문                             │
│      ↓                                  │
│  Supervisor (질문 의도 분류)             │
│      ↓                                  │
│  ┌────────┬─────────┬──────────┬──────┐ │
│  │Search  │Compare  │Recommend │Chat  │ │
│  │Agent   │Agent    │Agent     │      │ │
│  │ReAct   │ReAct    │ReAct     │LLM   │ │
│  └───┬────┴────┬────┴────┬─────┴──────┘ │
│      └─────────┴─────────┘              │
│           ↓ Tools                       │
│  graph_search / vector_search           │
└─────────────────────────────────────────┘
            ↓                    ↓
    Streamlit 챗봇 UI     Claude Desktop (MCP)
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
- **벡터 인덱스**: product_embeddings (384차원, cosine 유사도)

---

## 🤖 멀티에이전트 구조

### Supervisor 패턴

질문 의도를 LLM이 분류해 전문 에이전트로 조건 분기합니다.

| 에이전트 | 역할 | 도구 |
|---|---|---|
| Search Agent | 상품 검색 | graph_search, vector_search |
| Compare Agent | 상품 비교 | vector_search |
| Recommend Agent | 개인화 추천 | vector_search |
| Chat | 일반 대화 | LLM 직접 답변 |

### ReAct 루프

각 에이전트는 `create_react_agent`로 구현되어 도구 결과를 관찰하고 재시도 여부를 자율 결정합니다.

```
LLM 추론 → 도구 호출 → 결과 관찰 → 재추론 or 최종 답변
```

### 멀티턴 대화

`chat_history`를 공유 State로 관리해 이전 대화 맥락을 에이전트 간에 공유합니다.

---

## 🔌 MCP 서버 (Claude Desktop 연동)

FastMCP로 검색 도구를 Claude Desktop에 노출합니다.

```python
@mcp.tool()
def graph_search(category, brand, budget)   # 구조적 검색
def vector_search(query, category, budget)  # 의미 유사도 검색
def get_also_bought(product_title)          # 연관 상품 조회
```

Claude Desktop이 Neo4j DB를 직접 도구로 활용해 자체 추론과 결합한 답변을 생성합니다.

---

## 🛠️ 기술 스택

| 분류 | 기술 |
|---|---|
| 파이프라인 | Airflow 2.7.1, Kafka (KRaft) |
| 그래프 DB | Neo4j 5.12 + Vector Index |
| 임베딩 | HuggingFace all-MiniLM-L6-v2 |
| LLM | GPT-4o-mini |
| 에이전트 | LangGraph, create_react_agent |
| MCP | FastMCP |
| 평가 | RAGAS |
| UI | Streamlit |
| 인프라 | Docker, Docker Compose |

---

## ✨ 주요 기능

1. **멀티에이전트 라우팅** — Supervisor가 질문 의도 분류 후 전문 에이전트로 조건 분기
2. **ReAct 자기 루프** — 검색 결과가 없으면 조건 완화 후 자율 재시도
3. **Graph-RAG 검색** — 벡터 유사도 + 그래프 관계(ALSO_BOUGHT) 결합
4. **한국어 지원** — 한국어 질문 자동 번역 + 동의어 확장 후 임베딩
5. **멀티턴 대화** — chat_history 기반 이전 맥락 유지
6. **MCP 연동** — Claude Desktop에서 직접 Neo4j 검색 도구 활용

---

## 📈 성능 평가 (RAGAS)

| 지표 | 점수 | 설명 |
|---|---|---|
| Faithfulness | 0.845 | 답변이 DB 데이터에 근거하는 정도 |
| Answer Relevancy | 0.887 | 질문과 답변의 연관성 |
| Context Precision | 0.789 | 검색된 컨텍스트의 정확도 |
| Context Recall | 0.600 | 필요한 정보의 포함 정도 |

**Context Recall 한계:** 3만 건 샘플 데이터 사용으로 ALSO_BOUGHT 관계의 약 90%가 샘플 외 상품을 참조해 그래프 확장이 제한됩니다. 전체 데이터셋 적용 시 개선될 것으로 예상됩니다.

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
# Streamlit UI
streamlit run app.py
# http://localhost:8501

# MCP 서버 (Claude Desktop 연동)
python mcp_server.py
```

### 6. 성능 평가
```bash
python evaluate_ragas.py
```

---

## 💬 사용 예시

```
👤 블루투스 이어폰 추천해줘
🤖 블루투스 이어폰 추천 상품입니다:
   1. Bluetooth Headset V4.1 Wireless - $18.99
   2. Wireless Earbuds with Mic - $24.99

👤 1번이랑 2번 비교해줘
🤖 두 상품을 비교하면:
   | 항목 | Bluetooth Headset | Wireless Earbuds |
   | 가격 | $18.99 | $24.99 |
   ...

👤 내 취향에 맞게 하나만 골라줘
🤖 대화 내용을 보니 무선 + 가성비를 중시하시는 것 같아 1번을 추천드립니다.
```

---

## 📁 프로젝트 구조

```
amazon-graph-rag-recommender/
├── docker-compose.yml
├── dags/
│   ├── amazon_producer_v1.py       # Kafka Producer DAG
│   └── amazaon_consumer_v1.py      # Kafka Consumer → Neo4j DAG
├── data/
│   └── electronics_ontology_sample.json
├── update_neo4j.py                 # ALSO_BOUGHT 관계 구축
├── update_embedding.py             # HuggingFace 임베딩 생성
├── main.py                         # LangGraph 멀티에이전트
├── app.py                          # Streamlit UI
├── mcp_server.py                   # FastMCP 서버
└── evaluate_ragas.py               # RAGAS 성능 평가
```

---

## ⚠️ 한계점 및 개선 방향

- **Context Recall** — 샘플 데이터 한계로 그래프 확장 제한, 전체 데이터셋 적용 시 개선 예상
- **RAG 고도화** — 현재 상품 title 기반 임베딩, 상품 description/feature 텍스트 청킹 적용 예정
- **배포** — 현재 로컬 실행 수준, Docker + 클라우드 배포 예정
- **Handoff 패턴** — 현재 단방향 라우팅, 에이전트 간 결과 공유하는 Handoff 패턴 도입 예정
