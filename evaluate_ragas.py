"""
RAGAS 기반 Graph-RAG 검색 성능 평가
측정 지표: faithfulness, answer_relevancy, context_precision, context_recall
"""
import os
from ragas.metrics._faithfulness import faithfulness
from ragas.metrics._answer_relevance import answer_relevancy
from ragas.metrics._context_precision import context_precision
from ragas.metrics._context_recall import context_recall
from ragas.llms import LangchainLLMWrapper
from ragas import EvaluationDataset, SingleTurnSample, evaluate
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_neo4j import Neo4jGraph
from langchain_huggingface import HuggingFaceEmbeddings

# ===== 초기 설정 =====
graph = Neo4jGraph(url="bolt://localhost:7687", username="neo4j", password="airflow123")
llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")

# RAGAS용 LLM / Embeddings (경고 무시)
import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)
ragas_llm = LangchainLLMWrapper(llm)
ragas_embeddings = OpenAIEmbeddings(model="text-embedding-3-small")

# ===== 테스트 데이터셋 =====
TEST_CASES = [
    {
        "question": "Recommend bluetooth headphones under $50",
        "ground_truth": "There are bluetooth headphones available under $50 with wireless connectivity."
    },
    {
        "question": "What Samsung electronics products are available?",
        "ground_truth": "Samsung offers various electronics products including headphones and audio devices."
    },
    {
        "question": "Find wireless earbuds for running",
        "ground_truth": "Wireless earbuds suitable for running with secure fit and sweat resistance are available."
    },
    {
        "question": "What are some affordable speakers under $30?",
        "ground_truth": "There are portable bluetooth speakers available under $30 budget."
    },
    {
        "question": "Show me headphones in the electronics category",
        "ground_truth": "Various headphones are available in the electronics and headphones category."
    },
]


def run_vector_search(query: str) -> tuple[str, list[str]]:
    """순수 벡터 검색 후 (답변, 컨텍스트 리스트) 반환"""
    try:
        english_query = llm.invoke(f"""
            Translate to English and expand with synonyms: {query}
            결과는 단어들만 나열해줘.
        """).content.strip() or query
    except Exception:
        english_query = query

    query_vector = embeddings.embed_query(english_query)

    cypher = """
    CALL db.index.vector.queryNodes('product_embeddings', 20, $vector)
    YIELD node AS product, score
    OPTIONAL MATCH (product)-[:MANUFACTURED_BY]->(brand:Brand)
    OPTIONAL MATCH (product)-[:BELONGS_TO]->(category:Category)
    WITH product, score, brand, category
    WHERE score > 0.55
    RETURN DISTINCT
        product.title AS title,
        product.price AS price,
        brand.name AS brand,
        MIN(category.name) AS category,
        product.product_text AS product_text,
        score
    ORDER BY score DESC LIMIT 5
    """
    results = graph.query(cypher, {"vector": query_vector})

    if not results:
        return "No products found.", []

    contexts = [
        f"{r['title']} | Brand: {r.get('brand', 'N/A')} | Price: {r.get('price', 'N/A')} | Category: {r.get('category', 'N/A')}"
        + (f" | {r['product_text'][:200]}" if r.get('product_text') else "")
        for r in results
    ]

    context_text = "\n".join(contexts)
    answer = llm.invoke(f"""
        Based on these products from our database:
        {context_text}

        Answer this question: {query}
        Be concise and helpful.
    """).content.strip()

    return answer, contexts


def build_ragas_dataset() -> EvaluationDataset:
    """RAGAS 평가용 데이터셋 생성"""
    print("=" * 50)
    print("RAGAS 평가 데이터셋 생성 중...")
    print("=" * 50)

    samples = []
    for i, case in enumerate(TEST_CASES):
        print(f"\n[{i+1}/{len(TEST_CASES)}] 질문: {case['question']}")
        answer, context_list = run_vector_search(case["question"])
        print(f"  검색된 컨텍스트: {len(context_list)}개")
        print(f"  답변: {answer[:80]}...")

        samples.append(SingleTurnSample(
            user_input=case["question"],
            response=answer,
            retrieved_contexts=context_list,
            reference=case["ground_truth"],
        ))

    return EvaluationDataset(samples=samples)


def run_evaluation():
    dataset = build_ragas_dataset()

    print("\n" + "=" * 50)
    print("RAGAS 평가 실행 중...")
    print("=" * 50)

    result = evaluate(
        dataset=dataset,
        metrics=[faithfulness, answer_relevancy, context_precision, context_recall],
        llm=ragas_llm,
        embeddings=ragas_embeddings,
    )

    print("\n" + "=" * 50)
    print("📊 RAGAS 평가 결과")
    print("=" * 50)
    df = result.to_pandas()
    print(df[["user_input", "faithfulness", "answer_relevancy", "context_precision", "context_recall"]].to_string())

    print("\n📈 평균 점수:")
    for metric in ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]:
        score = df[metric].mean()
        bar = "█" * int(score * 10) + "░" * (10 - int(score * 10))
        print(f"  {metric:<22} {bar}  {score:.3f}")

    return result


if __name__ == "__main__":
    run_evaluation()
