from typing import TypedDict, List
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import create_react_agent
from langchain_openai import ChatOpenAI
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_neo4j import Neo4jGraph
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from pydantic import BaseModel, Field

# ===== 초기 설정 =====
graph = Neo4jGraph(url="bolt://localhost:7687", username="neo4j", password="airflow123")
llm = ChatOpenAI(model="gpt-4o-mini", temperature=0, max_tokens=2000)
embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")

# ===== 공유 State =====
class AgentState(TypedDict):
    question: str
    chat_history: List[dict]  # 에이전트 간 공유되는 대화 히스토리
    task: str                 # supervisor 결정: search | compare | recommend | chat
    final_answer: str

# ===== Supervisor 구조체 =====
class SupervisorDecision(BaseModel):
    task: str = Field(description="수행할 작업: 'search'(상품검색), 'compare'(두 상품 비교), 'recommend'(히스토리 기반 개인화추천), 'chat'(일반 대화)")

# ===== TOOLS (에이전트들이 공유) =====

@tool
def graph_search(category: str = "", brand: str = "", budget: int = 0) -> str:
    """카테고리/브랜드/예산이 명확할 때 Neo4j 그래프에서 직접 상품을 검색합니다."""
    print(f"🎯 graph_search 호출: category={category}, brand={brand}, budget={budget}")
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
    print(f"📦 graph_search 결과: {len(results)}개")
    return str(results) if results else "검색 결과 없음"

@tool
def vector_search(query: str, category: str = "", budget: int = 0) -> str:
    """모호한 질문이나 키워드 기반 검색 시 벡터 유사도로 상품을 검색합니다."""
    print(f"🔍 vector_search 호출: query={query}, category={category}, budget={budget}")
    # 한국어 → 영어 번역 + 동의어 확장
    try:
        english_query = llm.invoke(f"""
            Translate to English and expand with synonyms: {query}
            예시: "블루투스 이어폰" → "bluetooth earphone earbuds wireless headphone"
            결과는 단어들만 나열해줘.
        """).content.strip() or query
    except Exception:
        english_query = query
    print(f"🌐 번역: {english_query}")
    query_vector = embeddings.embed_query(english_query)
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
    print(f"📦 vector_search 결과: {len(results)}개")
    return str(results) if results else "검색 결과 없음"

# ===== 에이전트 정의 (각자 독립적인 ReAct 루프) =====

search_agent = create_react_agent(
    llm,
    tools=[graph_search, vector_search],
    prompt="""당신은 아마존 상품 검색 전문 에이전트입니다.

도구 선택 전략:
1. 브랜드/카테고리가 명확하면 graph_search 우선 사용
2. 모호한 질문이면 vector_search 사용
3. 결과가 2개 미만이면 조건을 완화해서 재검색 (예: budget 제거 → brand 제거)
4. 결과를 한국어로 친절하게 요약, 관련 없는 상품(책/의류 등)은 제외
5. 가격이 정상적인 값($숫자)이면 표시, 이상한 값이면 생략"""
)

compare_agent = create_react_agent(
    llm,
    tools=[vector_search],
    prompt="""당신은 상품 비교 전문 에이전트입니다.

비교 방법:
1. 대화 히스토리에 비교할 상품 정보(가격, 브랜드 등)가 이미 있으면 그 정보를 그대로 사용하세요. 새로 검색하지 마세요.
2. 히스토리에 정보가 없을 때만 vector_search로 검색하세요.
3. 가격, 브랜드, 카테고리 기준으로 비교표 형식으로 정리하세요.
4. 어떤 상황에 어떤 상품이 더 적합한지 추천 의견을 제시하세요.
5. 한국어로 친절하게 답변하세요."""
)

recommend_agent = create_react_agent(
    llm,
    tools=[vector_search],
    prompt="""당신은 개인화 추천 전문 에이전트입니다.

추천 방법:
1. 대화 히스토리에서 사용자 선호도(예산, 카테고리, 브랜드, 용도) 파악
2. 파악한 선호도 기반으로 vector_search 실행
3. 왜 이 상품을 추천하는지 이유를 함께 설명
4. 한국어로 친절하게 답변"""
)

# ===== SUPERVISOR =====

def supervisor(state: AgentState):
    """어떤 에이전트에게 작업을 위임할지 결정"""
    structured_llm = llm.with_structured_output(SupervisorDecision)
    history = state.get('chat_history', [])
    history_text = "\n".join([f"{m['role']}: {m['content']}" for m in history[-6:]]) if history else "없음"

    result = structured_llm.invoke(f"""
        대화 히스토리: {history_text}
        현재 질문: {state['question']}

        task 결정 기준:
        - search: 상품 검색/추천 요청
        - compare: 두 상품 비교 (예: "A랑 B 비교해줘")
        - recommend: 히스토리 기반 개인화 추천 (예: "내 취향에 맞는 거 골라줘")
        - chat: 일반 대화 (예: "왜 그래?", "고마워")
    """)
    print(f"🎯 Supervisor → {result.task}")
    return {"task": result.task}

def route_task(state: AgentState):
    return state.get("task", "search")

# ===== 에이전트 실행 노드 =====

def run_search_agent(state: AgentState):
    print("🔎 Search Agent 실행")
    history = state.get('chat_history', [])
    history_text = "\n".join([f"{m['role']}: {m['content']}" for m in history[-6:]]) if history else "없음"
    result = search_agent.invoke({
        "messages": [HumanMessage(content=f"대화 히스토리:\n{history_text}\n\n질문: {state['question']}")]
    })
    return {"final_answer": result["messages"][-1].content}

def run_compare_agent(state: AgentState):
    print("⚖️ Compare Agent 실행")
    history = state.get('chat_history', [])
    history_text = "\n".join([f"{m['role']}: {m['content']}" for m in history[-6:]]) if history else "없음"
    result = compare_agent.invoke({
        "messages": [HumanMessage(content=f"대화 히스토리:\n{history_text}\n\n질문: {state['question']}")]
    })
    return {"final_answer": result["messages"][-1].content}

def run_recommend_agent(state: AgentState):
    print("🎁 Recommend Agent 실행")
    history = state.get('chat_history', [])
    history_text = "\n".join([f"{m['role']}: {m['content']}" for m in history[-10:]]) if history else "없음"
    result = recommend_agent.invoke({
        "messages": [HumanMessage(content=f"대화 히스토리:\n{history_text}\n\n질문: {state['question']}")]
    })
    return {"final_answer": result["messages"][-1].content}

def run_chat(state: AgentState):
    print("💬 Chat 실행")
    history = state.get('chat_history', [])
    history_text = "\n".join([f"{m['role']}: {m['content']}" for m in history[-6:]]) if history else "없음"
    res = llm.invoke(f"""
        대화 히스토리: {history_text}
        현재 질문: {state['question']}
        친절한 쇼핑 어시스턴트 말투로 한국어 답변:
    """)
    return {"final_answer": res.content}

# ===== 워크플로우 조립 =====
workflow = StateGraph(AgentState)

workflow.add_node("supervisor", supervisor)
workflow.add_node("search_agent", run_search_agent)
workflow.add_node("compare_agent", run_compare_agent)
workflow.add_node("recommend_agent", run_recommend_agent)
workflow.add_node("chat", run_chat)

workflow.set_entry_point("supervisor")
workflow.add_conditional_edges("supervisor", route_task, {
    "search":    "search_agent",
    "compare":   "compare_agent",
    "recommend": "recommend_agent",
    "chat":      "chat",
})
workflow.add_edge("search_agent",    END)
workflow.add_edge("compare_agent",   END)
workflow.add_edge("recommend_agent", END)
workflow.add_edge("chat",            END)

app = workflow.compile()

if __name__ == "__main__":
    print("=== 🛍️ 아마존 상품 추천 멀티 에이전트 시작 ===")
    print("(종료하려면 'exit' 또는 'quit'을 입력하세요)")

    chat_history = []

    while True:
        user_input = input("\n👤 사용자: ")

        if user_input.lower() in ['exit', 'quit', 'q', '종료']:
            print("👋 대화를 종료합니다. 이용해 주셔서 감사합니다!")
            break

        try:
            result = app.invoke({"question": user_input, "chat_history": chat_history})
            answer = result['final_answer']
            print(f"\n🤖 에이전트: {answer}")

            chat_history.append({"role": "user", "content": user_input})
            chat_history.append({"role": "assistant", "content": answer})

        except Exception as e:
            print(f"❌ 오류가 발생했습니다: {e}")
