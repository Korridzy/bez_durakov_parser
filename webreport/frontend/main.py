"""
Streamlit frontend for the web reporting system.
Provides UI with chat and report views.
"""
import streamlit as st
import requests
import pandas as pd
import json
from datetime import datetime
from typing import Dict, Any, Optional, List
import os
import uuid

# Configuration
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")

# Page configuration
st.set_page_config(
    page_title="Game Data Reports",
    page_icon="🎮",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: bold;
        color: #1E88E5;
        margin-bottom: 1rem;
    }
    .chat-message {
        padding: 1rem;
        border-radius: 0.5rem;
        margin-bottom: 0.5rem;
    }
    .user-message {
        background-color: #E3F2FD;
        border-left: 4px solid #1E88E5;
    }
    .assistant-message {
        background-color: #F5F5F5;
        border-left: 4px solid #757575;
    }
    .report-section {
        background-color: #FFFFFF;
        padding: 1.5rem;
        border-radius: 0.5rem;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
</style>
""", unsafe_allow_html=True)


def init_session_state():
    """Initialize session state variables."""
    if 'session_id' not in st.session_state:
        st.session_state.session_id = str(uuid.uuid4())
    if 'view' not in st.session_state:
        st.session_state.view = 'chat'
    if 'chat_history' not in st.session_state:
        st.session_state.chat_history = []
    if 'current_report' not in st.session_state:
        st.session_state.current_report = None
    if 'report_data' not in st.session_state:
        st.session_state.report_data = None


def check_api_health() -> bool:
    """Check if API is available."""
    try:
        response = requests.get(f"{API_BASE_URL}/health", timeout=2)
        return response.status_code == 200
    except requests.exceptions.RequestException:
        return False


def send_chat_message(message: str) -> Dict[str, Any]:
    """Send chat message to API."""
    try:
        response = requests.post(
            f"{API_BASE_URL}/api/chat",
            json={"message": message, "session_id": st.session_state.session_id},
            timeout=30
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "message": "Failed to communicate with backend"
        }


def get_conversation_history() -> List[Dict[str, Any]]:
    """Get conversation history from API."""
    try:
        response = requests.get(
            f"{API_BASE_URL}/api/history/{st.session_state.session_id}",
            timeout=10
        )
        response.raise_for_status()
        data = response.json()
        return data.get("history", [])
    except:
        return []


def clear_conversation():
    """Clear conversation history."""
    try:
        requests.post(f"{API_BASE_URL}/api/clear/{st.session_state.session_id}", timeout=10)
        st.session_state.chat_history = []
        st.session_state.current_report = None
        st.session_state.report_data = None
    except Exception as e:
        st.error(f"Failed to clear history: {e}")


def render_chat_view():
    """Render the chat view."""
    st.markdown('<div class="main-header">💬 Чат с AI-агентом</div>', unsafe_allow_html=True)

    # Chat interface
    st.markdown("### Опишите требования к отчёту")
    st.markdown("*Например: 'покажи все игры', 'топ 10 команд', 'статистика команды X'*")

    # Chat input
    with st.form(key='chat_form', clear_on_submit=True):
        user_input = st.text_area(
            "Ваше сообщение:",
            height=100,
            placeholder="Введите требования к отчёту..."
        )
        col1, col2 = st.columns([1, 5])
        with col1:
            submit_button = st.form_submit_button("Отправить", use_container_width=True)
        with col2:
            clear_button = st.form_submit_button("Очистить историю", use_container_width=True)

    if clear_button:
        clear_conversation()
        st.rerun()

    if submit_button and user_input:
        with st.spinner('Генерация отчёта...'):
            # Add user message to history
            st.session_state.chat_history.append({
                "role": "user",
                "content": user_input,
                "timestamp": datetime.now().isoformat()
            })

            # Send to API
            response = send_chat_message(user_input)

            # Add response to history
            st.session_state.chat_history.append({
                "role": "assistant",
                "content": response,
                "timestamp": datetime.now().isoformat()
            })

            # Update current report
            if response.get("success"):
                st.session_state.current_report = response.get("message")
                st.session_state.report_data = response.get("data")
                st.success("✅ Отчёт сгенерирован! Переключитесь на вкладку 'Отчёт' для просмотра.")
            else:
                st.error(f"❌ Ошибка: {response.get('error', 'Unknown error')}")

            st.rerun()

    # Display chat history
    st.markdown("---")
    st.markdown("### История диалога")

    if not st.session_state.chat_history:
        st.info("История диалога пуста. Начните новый диалог выше.")
    else:
        for msg in reversed(st.session_state.chat_history[-10:]):  # Show last 10 messages
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            timestamp = msg.get("timestamp", "")

            if role == "user":
                st.markdown(f'<div class="chat-message user-message">', unsafe_allow_html=True)
                st.markdown(f"**👤 Пользователь** *({timestamp[:19]})*")
                st.markdown(f"{content}")
                st.markdown('</div>', unsafe_allow_html=True)
            else:
                st.markdown(f'<div class="chat-message assistant-message">', unsafe_allow_html=True)
                st.markdown(f"**🤖 Ассистент** *({timestamp[:19]})*")
                if isinstance(content, dict):
                    if content.get("success"):
                        st.markdown(f"✅ {content.get('message', 'Отчёт готов')}")
                    else:
                        st.markdown(f"❌ {content.get('error', 'Ошибка')}")
                else:
                    st.markdown(f"{content}")
                st.markdown('</div>', unsafe_allow_html=True)


def render_report_view():
    """Render the report view."""
    st.markdown('<div class="main-header">📊 Отчёт по данным игр</div>', unsafe_allow_html=True)

    if st.session_state.report_data is None:
        st.info("📝 Отчёт ещё не сгенерирован. Перейдите в чат и опишите требования к отчёту.")

        # Show some example queries
        st.markdown("### Примеры запросов:")
        st.markdown("""
        - **Все игры**: "покажи все игры"
        - **Топ команд**: "топ 10 команд по очкам"
        - **Статистика команды**: "статистика команды [название]"
        - **Очки команд**: "покажи очки всех команд"
        """)
        return

    # Display current report
    st.markdown(f"### {st.session_state.current_report or 'Текущий отчёт'}")

    try:
        data = st.session_state.report_data

        if isinstance(data, list) and len(data) > 0:
            # Convert to DataFrame for better display
            df = pd.DataFrame(data)

            # Display metrics if available
            st.markdown("#### Основные показатели")
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Всего записей", len(df))
            with col2:
                if 'total_points' in df.columns:
                    st.metric("Средние очки", f"{df['total_points'].mean():.2f}")
            with col3:
                if 'game_date' in df.columns:
                    st.metric("Уникальных дат", df['game_date'].nunique())

            # Display table
            st.markdown("#### Данные")
            st.dataframe(df, use_container_width=True, height=400)

            # Download button
            csv = df.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 Скачать CSV",
                data=csv,
                file_name=f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv"
            )

            # Charts if numeric data available
            numeric_cols = df.select_dtypes(include=['float64', 'int64']).columns.tolist()
            if numeric_cols and len(df) > 0:
                st.markdown("#### Визуализация")

                chart_col = st.selectbox("Выберите колонку для графика:", numeric_cols)
                if chart_col:
                    st.bar_chart(df.set_index(df.columns[0])[chart_col])

        elif isinstance(data, dict):
            # Display dict data
            st.json(data)

        else:
            st.write(data)

    except Exception as e:
        st.error(f"Ошибка отображения данных: {e}")
        st.write("Сырые данные:")
        st.write(st.session_state.report_data)


def main():
    """Main application."""
    init_session_state()

    # Sidebar
    with st.sidebar:
        st.markdown("## 🎮 Game Data Reports")
        st.markdown("---")

        # Check API health
        if check_api_health():
            st.success("✅ API подключен")
        else:
            st.error("❌ API недоступен")
            st.markdown(f"Проверьте, что сервер запущен на {API_BASE_URL}")

        st.markdown("---")

        # View selector
        st.markdown("### Навигация")
        view = st.radio(
            "Выберите представление:",
            options=['chat', 'report'],
            format_func=lambda x: '💬 Чат' if x == 'chat' else '📊 Отчёт',
            key='view_selector'
        )
        st.session_state.view = view

        st.markdown("---")

        # Quick actions
        st.markdown("### Быстрые действия")
        if st.button("🔄 Обновить", use_container_width=True):
            st.rerun()

        if st.button("🗑️ Очистить чат", use_container_width=True):
            clear_conversation()
            st.rerun()

        st.markdown("---")
        st.markdown("### О системе")
        st.markdown("""
        Эта система использует:
        - **FastAPI** для REST API
        - **Streamlit** для UI
        - **AutoGen** для агентов
        - **SQLAlchemy** для БД
        """)

    # Main content
    if st.session_state.view == 'chat':
        render_chat_view()
    else:
        render_report_view()


if __name__ == "__main__":
    main()

