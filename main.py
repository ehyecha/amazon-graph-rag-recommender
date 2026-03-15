import os
from typing import TypedDict, List, Optional
from langgraph.graph import StateGraph, END
from langchain_openai import ChatOpenAI
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_neo4j import Neo4jGraph
from pydantic import BaseModel, Field

# 1. 초기 설정 (DB 및 LLM 연결)
graph = Neo4jGraph(url="bolt://localhost:7687", username="neo4j", password="airflow123")
llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
# 2. 에이전트 상태(State) 정의
class AgentState(TypedDict):
    question: str
    english_question: str  # 추가!
    category: str
    brand: Optional[str]
    budget: Optional[int]
    cypher_query: str
    db_results: List[dict]
    final_answer: str

# 1. 추출할 데이터의 규격 정의
class SearchParams(BaseModel):
    category: str = Field(description="제품 카테고리 (예: Watches, Electronics)")
    brand: str = Field(description="추출된 브랜드 이름 전체 (예: 5.11, Rand McNally, Samsung)")
    budget: Optional[int] = Field(description="예산 숫자")

# 3. 노드(Node) 함수 정의
def analyze_intent(state: AgentState):
    # LLM이 SearchParams 규격에 맞춰서만 출력하도록 설정
    structured_llm = llm.with_structured_output(SearchParams)
    english_q = llm.invoke(f"""
        Translate to English and expand with synonyms: {state['question']}
        예시: "랩탑" → "laptop notebook computer"
        예시: "이어폰" → "earphone earbuds headphone"
        결과는 단어들만 나열해줘.
        """).content
    print(f"🌐 번역: {english_q}")

    """사용자의 질문을 분석하여 검색 조건을 추출합니다."""
    prompt = f"""사용자 질문: {state['question']}
    위 질문에서 다음 정보를 JSON 형태로만 추출해줘.
    - category: (예: Watches)
    - brand: (언급된 경우만)
    - budget: (숫자만, 없으면 null, 반드시 달러$ 기준으로 추출. 예: "50이하" → 50, "100달러" → 100)"""
    
    result = structured_llm.invoke(prompt)
    print(f"✅ 추출된 브랜드: {result.brand}")
    print(f"category: {result.category}")
    print("budget:", result.budget)
    return { "english_question": english_q, "category": result.category, "budget": result.budget, "brand": result.brand}

def finalize_response(state: AgentState):
    """한국어 답변 생성"""
    print("✍️ 답변 생성 중...")

    if not state.get('db_results'):
        prompt = f"""
        사용자 질문: {state['question']}
        [검색된 상품]: {str(state['db_results'])}

        위 데이터만 바탕으로 친절한 한국어로 상품을 추천해주세요.
        - 반드시 데이터에 있는 내용만 추천하세요
        - 검색된 상품을 모두 리스트로 보여주세요. 하나만 추천하지 마세요
        - 가격이 정상적인 값($숫자)이면 표시하고, 이상한 값이면 그냥 생략하세요
        - 상품명, 가격(있으면), 특징을 간결하게 설명하세요
        - 친절한 쇼핑 어시스턴트 말투로 답변하세요
        """
    else:
        prompt = f"""
        사용자 질문: {state['question']}
        [검색된 상품]: {str(state['db_results'])}
        
        위 데이터를 바탕으로 친절한 한국어로 추천해주세요.
        - 검색된 상품을 모두 리스트로 보여주세요
        - 가격이 정상적인 값($숫자)이면 표시하고 이상한 값이면 생략하세요
        - also_bought 데이터가 있으면 "이 상품을 구매한 고객이 함께 구매한 상품"도 함께 안내해주세요
        - 친절한 쇼핑 어시스턴트 말투로 답변하세요
        """

    res = llm.invoke(prompt)
    return {"final_answer": res.content}

def semantic_search(state: AgentState):
    print("🔍 벡터 검색 중...")
    print(f"💰 예산: {state.get('budget')}")

    query_vector = embeddings.embed_query(state['english_question'])

    # WHERE 조건 미리 구성
    conditions = ["score > 0.60"]
    params = {"vector": query_vector}

    if state.get('brand'):
        conditions.append(f"(brand IS NULL OR brand.name =~ '(?i).*{state['brand']}.*')")
    if state.get('budget'):
        conditions.append(f"toFloat(replace(product.price, '$', '')) <= {state['budget']}")
        print(f"💰 예산 필터 추가: <= {state['budget']}")

    where_clause = " AND ".join(conditions)

    search_query = f"""
    CALL db.index.vector.queryNodes('product_embeddings', 20, $vector)
    YIELD node AS product, score
    OPTIONAL MATCH (product)-[:ALSO_BOUGHT]->(related:Product)
    OPTIONAL MATCH (product)-[:MANUFACTURED_BY]->(brand:Brand)
    OPTIONAL MATCH (product)-[:BELONGS_TO]->(category:Category)
    WHERE {where_clause}
    RETURN DISTINCT
        product.title AS title,
        product.price AS price,
        MIN(category.name) AS category,
        brand.name AS brand,
        collect(DISTINCT related.title)[0..3] AS also_bought,
        score
    ORDER BY score DESC
    LIMIT 5
    """

    print(f"🛠️ 최종 쿼리: {search_query}")
    results = graph.query(search_query, params)
    print(f"📦 검색 결과: {len(results)}개")
    return {"db_results": results}
# def semantic_search(state: AgentState):
#     """벡터 검색 (핵심!)"""
#     print("🔍 벡터 검색 중...")
#     print(f"💰 예산: {state.get('budget')}")  # 예산 확인

#     query_vector = embeddings.embed_query(state['english_question'])

#     search_query = """
#     CALL db.index.vector.queryNodes('product_embeddings', 20, $vector)
#     YIELD node AS product, score
#     OPTIONAL MATCH (product)-[:ALSO_BOUGHT]->(related:Product)
#     OPTIONAL MATCH (product)-[:MANUFACTURED_BY]->(brand:Brand)
#     OPTIONAL MATCH (product)-[:BELONGS_TO]->(category:Category)
#     WHERE score > 0.60
#     """

#     conditions = []
#     params = {"vector": query_vector}

#     if state.get('brand'):
#         conditions.append(f"brand.name =~ '(?i).*{state['brand']}.*'")
#     if state.get('budget'):
#         conditions.append(f"product.price <= {state['budget']}")
#         #conditions.append(f" v <= {state['budget']}")
#         print(f"💰 예산 필터 추가: toFloat(product.price) <= {state['budget']}")

#     if conditions:
#         search_query += " AND " + " AND ".join(conditions)

#     search_query += """
#     RETURN DISTINCT
#         product.title AS title,
#         product.price AS price,
#         MIN(category.name) AS category,
#         brand.name AS brand,
#         collect(DISTINCT related.title)[0..3] AS also_bought,
#         score
#     ORDER BY score DESC
#     LIMIT 5
#     """

#     print(f"🛠️ 최종 쿼리: {search_query}")
#     results = graph.query(search_query, params)
#     print(f"📦 검색 결과: {len(results)}개")
#     return {"db_results": results}


# 4. 그래프(Workflow) 조립
workflow = StateGraph(AgentState)

workflow.add_node("analyzer", analyze_intent)
workflow.add_node("semantic_search", semantic_search)
workflow.add_node("responder", finalize_response)

workflow.set_entry_point("analyzer")
workflow.add_edge("analyzer", "semantic_search")   # 변경
workflow.add_edge("semantic_search", "responder")  # 변경
workflow.add_edge("responder", END)

app = workflow.compile()

if __name__ == "__main__":
    print("=== 🛍️ 아마존 상품 추천 에이전트 대화 시작 ===")
    print("(종료하려면 'exit' 또는 'quit'을 입력하세요)")
    
    while True:
        # 1. 사용자 입력 받기
        user_input = input("\n👤 사용자: ")

        
        # 2. 종료 조건 체크
        if  user_input.lower() in ['exit', 'quit', 'q', '종료']:
            print("👋 대화를 종료합니다. 이용해 주셔서 감사합니다!")
            break
            
        # 3. 에이전트 실행
        try:
            # 질문 전달 및 결과 수신
            result = app.invoke({"question":  user_input})
            
            # 4. 답변 출력
            print(f"\n🤖 에이전트: {result['final_answer']}")
            
        except Exception as e:
            print(f"❌ 오류가 발생했습니다: {e}")