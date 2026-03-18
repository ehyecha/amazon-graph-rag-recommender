from ragas.llms import LangchainLLMWrapper
from ragas.embeddings import LangchainEmbeddingsWrapper
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from datasets import Dataset
from ragas import evaluate
from ragas.metrics import faithfulness, answer_relevancy, context_precision
from main import app  # 현영님 agent.py 임포트

# 1. 테스트 질문 목록
questions = [
    "블루투스 이어폰 추천해줘",
    "삼성 제품 추천해줘",
    "50달러 이하 헤드폰 추천해줘",
    "방수 이어폰 찾고 있어",
    "노이즈캔슬링 이어폰 있어?",
    "애플 제품 추천해줘",
    "100달러 이하 스피커 있어?",
    "충전케이블 추천해줘",
    "게이밍 헤드셋 찾고 있어",
    "무선 마우스 추천해줘"
]

# 2. 실제 챗봇 실행해서 데이터 수집
test_data = []

for q in questions:
    print(f"질문 처리 중: {q}")
    result = app.invoke({"question": q})
    
    # contexts: db_results를 문자열로 변환
    contexts = [str(r) for r in result['db_results']]
    
    test_data.append({
        "question": q,
        "answer": result['final_answer'],
        "contexts": contexts if contexts else ["검색 결과 없음"]
    })
    print(f"완료: {q}")

# 3. RAGAS 평가
dataset = Dataset.from_list(test_data)

evaluator_llm = LangchainLLMWrapper(
    ChatOpenAI(
        model="gpt-4o-mini",
        max_tokens=2000
    )
)

# 임베딩 설정 추가
evaluator_embeddings = LangchainEmbeddingsWrapper(
    OpenAIEmbeddings()
)

# 3번 실행해서 평균 내기
# nan 제거하고 평균 내기
import math

faithfulness_scores = []
relevancy_scores = []

for i in range(3):
    result = evaluate(
        dataset, 
        metrics=[faithfulness, answer_relevancy], 
        llm=evaluator_llm, 
        embeddings=evaluator_embeddings
    )
    
    f_score = result['faithfulness']
    r_score = result['answer_relevancy']
    
    f_val = sum(f_score)/len(f_score) if isinstance(f_score, list) else float(f_score)
    r_val = sum(r_score)/len(r_score) if isinstance(r_score, list) else float(r_score)
    
    # nan이면 추가 안 함
    if not math.isnan(f_val):
        faithfulness_scores.append(f_val)
    if not math.isnan(r_val):
        relevancy_scores.append(r_val)
        
    print(f"{i+1}번째: Faithfulness={f_val:.4f}, Relevancy={r_val:.4f}")

# nan 제외하고 평균
if faithfulness_scores:
    print(f"\n평균 Faithfulness: {sum(faithfulness_scores)/len(faithfulness_scores):.4f}")
if relevancy_scores:
    print(f"평균 Answer Relevancy: {sum(relevancy_scores)/len(relevancy_scores):.4f}")