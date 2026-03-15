import streamlit as st
from main import app  # 기존 워크플로우 그대로 import

# 페이지 설정
st.set_page_config(
    page_title="Amazon Graph-RAG 추천 시스템",
    page_icon="🛍️",
    layout="centered"
)

st.title("🛍️ Amazon 상품 추천 시스템")
st.caption("Graph-RAG 기반 AI 쇼핑 어시스턴트 | Neo4j + LangGraph + GPT-4o-mini")

# 대화 히스토리 초기화
if "messages" not in st.session_state:
    st.session_state.messages = []
    # 첫 인사말
    st.session_state.messages.append({
        "role": "assistant",
        "content": "안녕하세요! 아마존 상품 추천 AI입니다 😊\n\n어떤 상품을 찾고 계신가요?\n\n예시: '블루투스 이어폰 추천해줘', '50달러 이하 스피커 있어?'"
    })

# 대화 히스토리 출력
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# 사용자 입력
if user_input := st.chat_input("상품을 검색해보세요..."):

    # 사용자 메시지 추가
    st.session_state.messages.append({
        "role": "user",
        "content": user_input
    })
    with st.chat_message("user"):
        st.markdown(user_input)

    # 에이전트 실행
    with st.chat_message("assistant"):
        with st.spinner("검색 중..."):
            try:
                result = app.invoke({"question": user_input})
                answer = result["final_answer"]
            except Exception as e:
                answer = f"오류가 발생했습니다: {e}"

        st.markdown(answer)

    # 답변 히스토리 추가
    st.session_state.messages.append({
        "role": "assistant",
        "content": answer
    })