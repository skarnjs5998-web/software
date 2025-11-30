import streamlit as st
import pandas as pd
from github import Github
from io import StringIO
from datetime import datetime
import plotly.express as px

# ---------------------------------------------------------
# 1. 설정 및 Github 연결 함수
# ---------------------------------------------------------
st.set_page_config(page_title="인하대 출판부 재고 관리", layout="wide")


@st.cache_data(ttl=60)
def load_data_from_github(file_name):
    try:
        g = Github(st.secrets["github"]["token"])
        repo = g.get_repo(st.secrets["github"]["repo_name"])
        contents = repo.get_contents(file_name)

        # [핵심 수정 1] utf-8-sig로 BOM 제거
        decoded = contents.decoded_content.decode("utf-8-sig")

        df = pd.read_csv(StringIO(decoded))

        # [핵심 수정 2] 앞뒤 공백 제거 + 특수 공백(\xa0) 제거
        # 눈에 안 보이는 공백까지 확실하게 처리합니다.
        df.columns = df.columns.str.strip().str.replace("\xa0", " ")

        return df
    except Exception as e:
        st.error(f"데이터 로드 실패 ({file_name}): {e}")
        return pd.DataFrame()


def save_data_to_github(df, file_name, message):
    try:
        g = Github(st.secrets["github"]["token"])
        repo = g.get_repo(st.secrets["github"]["repo_name"])
        contents = repo.get_contents(file_name)

        csv_buffer = StringIO()
        df.to_csv(csv_buffer, index=False)
        new_content = csv_buffer.getvalue()

        repo.update_file(contents.path, message, new_content, contents.sha)
        st.cache_data.clear()
        return True
    except Exception as e:
        st.error(f"데이터 저장 실패: {e}")
        return False


# ---------------------------------------------------------
# 2. 데이터 로드
# ---------------------------------------------------------
df_inventory = load_data_from_github("inventory.csv")
df_transactions = load_data_from_github("transactions.csv")
df_orders = load_data_from_github("orders.csv")

if df_inventory.empty:
    st.warning("재고 데이터가 없습니다. inventory.csv를 확인하세요.")
    st.stop()

# ---------------------------------------------------------
# 3. 사용자 구분 및 보안
# ---------------------------------------------------------
st.sidebar.title("🔐 로그인 / 모드 설정")
user_mode = st.sidebar.radio("접속 모드", ["외부 이용자(Guest)", "내부 이용자(Admin)"])

is_admin = False

if user_mode == "내부 이용자(Admin)":
    password = st.sidebar.text_input("관리자 비밀번호", type="password")
    if password == st.secrets["admin"]["password"]:
        is_admin = True
        st.sidebar.success("✅ 관리자 인증 완료")
    else:
        st.sidebar.warning("비밀번호를 입력하세요.")
else:
    st.sidebar.info("외부 이용자는 '주문 청구'와 '현재 재고'만 이용 가능합니다.")

# ---------------------------------------------------------
# 4. 메뉴 구성
# ---------------------------------------------------------
menu_options = ["주문 청구", "현재 재고"]
if is_admin:
    menu_options += ["입출고 입력", "거래 기록", "알림", "리포트 및 분석"]

choice = st.title("📚 인하대 출판부 재고 관리 시스템")
selected_menu = st.sidebar.selectbox("메뉴 선택", menu_options)

# ---------------------------------------------------------
# 5. 기능 구현
# ---------------------------------------------------------

# === [1] 현재 재고 (UI 개선 적용) ===
if selected_menu == "현재 재고":
    st.subheader("🔍 현재 재고 현황")

    col1, col2 = st.columns([3, 1])
    with col1:
        search_term = st.text_input("검색 (책 이름 또는 ISBN)", placeholder="검색어를 입력하세요...")

    # 검색 로직
    if search_term:
        # astype(str)을 사용하여 데이터 타입 불일치 오류 방지
        mask = df_inventory['책 이름'].astype(str).str.contains(search_term) | df_inventory['ISBN'].astype(
            str).str.contains(search_term)
        result = df_inventory[mask]
    else:
        result = df_inventory

    # 스타일링하여 표시 (column_config 활용)
    # 데이터프레임에 실제 컬럼이 있는지 확인 후 표시
    st.dataframe(
        result,
        column_config={
            "가격": st.column_config.NumberColumn(format="%d원"),
            "현재 수량": st.column_config.NumberColumn(format="%d권"),
        },
        use_container_width=True,
        hide_index=True
    )


# === [2] 주문 청구 ===
elif selected_menu == "주문 청구":
    st.header("📝 도서 주문 청구")

    with st.form("order_form"):
        if '책 이름' in df_inventory.columns:
            book_list = df_inventory['책 이름'].tolist()
            client_name = st.text_input("거래처/주문자명")
            selected_book = st.selectbox("책 이름 선택", book_list)
            order_qty = st.number_input("주문 수량", min_value=1, value=10)

            submitted = st.form_submit_button("주문하기")

            if submitted:
                if not client_name:
                    st.error("거래처/주문자명을 입력해주세요.")
                else:
                    new_order = pd.DataFrame({
                        "일시": [datetime.now().strftime("%Y-%m-%d %H:%M:%S")],
                        "거래처": [client_name],
                        "책 이름": [selected_book],
                        "주문 수량": [order_qty],
                        "상태": ["미처리"]
                    })
                    updated_orders = pd.concat([df_orders, new_order], ignore_index=True)
                    if save_data_to_github(updated_orders, "orders.csv", f"Order request: {client_name}"):
                        st.success(f"주문이 접수되었습니다.\n\n거래처: {client_name}, 책: {selected_book}, 수량: {order_qty}")
        else:
            st.error(f"'책 이름' 컬럼을 찾을 수 없습니다. 현재 인식된 컬럼: {df_inventory.columns.tolist()}")

# === [3] 입출고 입력 (관리자) ===
elif selected_menu == "입출고 입력" and is_admin:
    st.header("🚚 입출고 관리")

    if '책 이름' not in df_inventory.columns:
        st.error(f"'책 이름' 컬럼이 없습니다. 현재 인식된 컬럼: {df_inventory.columns.tolist()}")
    else:
        with st.form("transaction_form"):
            tx_type = st.radio("거래 유형", ["입고", "출고", "파손", "반품"])
            client_name = st.text_input("거래처 (파손 시 생략 가능)")

            book_list = df_inventory['책 이름'].tolist()
            selected_book = st.selectbox("책 이름", book_list)
            qty = st.number_input("수량", min_value=1)

            submitted = st.form_submit_button("입력 완료")

            if submitted:
                if tx_type != "파손" and not client_name:
                    st.error("거래처를 입력해주세요.")
                else:
                    current_book_info = df_inventory[df_inventory['책 이름'] == selected_book].iloc[0]
                    current_qty = int(current_book_info['현재 수량'])
                    price = int(current_book_info['가격'])

                    new_qty = current_qty
                    if tx_type in ["입고", "반품"]:
                        new_qty += qty
                    elif tx_type in ["출고", "파손"]:
                        if current_qty < qty:
                            st.error("재고가 부족합니다.")
                            st.stop()
                        new_qty -= qty

                    df_inventory.loc[df_inventory['책 이름'] == selected_book, '현재 수량'] = new_qty

                    new_tx = pd.DataFrame({
                        "일시": [datetime.now().strftime("%Y-%m-%d %H:%M:%S")],
                        "거래처": [client_name if client_name else "N/A"],
                        "책 이름": [selected_book],
                        "수량": [qty],
                        "가격": [price],
                        "유형": [tx_type]
                    })

                    updated_tx = pd.concat([df_transactions, new_tx], ignore_index=True)

                    save_inventory = save_data_to_github(df_inventory, "inventory.csv",
                                                         f"Update Inventory: {selected_book}")
                    save_tx = save_data_to_github(updated_tx, "transactions.csv",
                                                  f"Add Tx: {tx_type} - {selected_book}")

                    if save_inventory and save_tx:
                        st.success(f"{tx_type} 처리 완료! (현재 재고: {new_qty}권)")

# === [4] 거래 기록 (관리자) ===
elif selected_menu == "거래 기록" and is_admin:
    st.header("📋 전체 거래 내역")
    if not df_transactions.empty:
        df_sorted = df_transactions.sort_values(by="일시", ascending=False)
        st.dataframe(df_sorted, use_container_width=True)
    else:
        st.info("거래 기록이 없습니다.")

# === [5] 알림 (관리자) ===
elif selected_menu == "알림" and is_admin:
    st.header("🔔 알림 센터")

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("1. 신규 주문 요청")
        if not df_orders.empty and '상태' in df_orders.columns:
            pending_orders = df_orders[df_orders['상태'] == '미처리']
            if not pending_orders.empty:
                for idx, row in pending_orders.iterrows():
                    st.warning(f"📢 **{row['거래처']}**에서 **{row['책 이름']}** {row['주문 수량']}권 주문 요청")
            else:
                st.success("신규 주문이 없습니다.")
        else:
            st.info("주문 데이터가 없습니다.")

    with col2:
        st.subheader("2. 안전 재고 미달 알림")
        if '현재 수량' in df_inventory.columns and '안전 재고' in df_inventory.columns:
            df_inventory['현재 수량'] = pd.to_numeric(df_inventory['현재 수량'])
            df_inventory['안전 재고'] = pd.to_numeric(df_inventory['안전 재고'])
            low_stock = df_inventory[df_inventory['현재 수량'] <= df_inventory['안전 재고']]

            if not low_stock.empty:
                for idx, row in low_stock.iterrows():
                    st.error(f"🚨 **{row['책 이름']}** 재고 부족! (현재: {row['현재 수량']} / 안전선: {row['안전 재고']})")
            else:
                st.success("모든 재고가 안전합니다.")
        else:
            st.error("재고 데이터 컬럼 오류")

# === [6] 리포트 및 분석 (관리자) ===
elif selected_menu == "리포트 및 분석" and is_admin:
    st.header("📈 데이터 분석 리포트")

    if not df_transactions.empty:
        df_transactions['일시'] = pd.to_datetime(df_transactions['일시'])
        df_inventory['현재 수량'] = pd.to_numeric(df_inventory['현재 수량'])
        df_inventory['가격'] = pd.to_numeric(df_inventory['가격'])

        tab1, tab2, tab3 = st.tabs(["월간 판매량", "재고 자산 평가", "거래처별 반품률"])

        with tab1:
            st.subheader("월별 도서 판매 추이")
            sales_df = df_transactions[df_transactions['유형'] == '출고'].copy()
            if not sales_df.empty:
                sales_df['월'] = sales_df['일시'].dt.strftime('%Y-%m')
                monthly_sales = sales_df.groupby(['월', '책 이름'])['수량'].sum().reset_index()
                fig = px.bar(monthly_sales, x='월', y='수량', color='책 이름', barmode='group')
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("출고 기록이 없습니다.")

        with tab2:
            st.subheader("현재 재고 총 가치")
            total_value = (df_inventory['현재 수량'] * df_inventory['가격']).sum()
            st.metric(label="총 재고 자산 가치", value=f"{total_value:,.0f} 원")
            df_inventory['자산 가치'] = df_inventory['현재 수량'] * df_inventory['가격']
            st.dataframe(df_inventory[['책 이름', '현재 수량', '가격', '자산 가치']])

        with tab3:
            st.subheader("거래처별 반품률 분석")
            tx_valid = df_transactions[df_transactions['거래처'] != 'N/A'].copy()
            if not tx_valid.empty:
                sales_by_client = tx_valid[tx_valid['유형'] == '출고'].groupby('거래처')['수량'].sum()
                returns_by_client = tx_valid[tx_valid['유형'] == '반품'].groupby('거래처')['수량'].sum()
                analysis_df = pd.DataFrame({'총 판매량': sales_by_client, '총 반품량': returns_by_client}).fillna(0)
                analysis_df['반품률(%)'] = (analysis_df['총 반품량'] / analysis_df['총 판매량']) * 100
                analysis_df['반품률(%)'] = analysis_df['반품률(%)'].fillna(0).round(2)
                st.dataframe(analysis_df)
            else:
                st.info("거래 데이터 부족")