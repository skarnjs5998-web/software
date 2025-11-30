import streamlit as st
import pandas as pd
from github import Github
from io import StringIO
from datetime import datetime
import plotly.express as px

# ---------------------------------------------------------
# 1. 설정 및 Github 연결 함수 (Constraint 3, 10-1)
# ---------------------------------------------------------
st.set_page_config(page_title="인하대 출판부 재고 관리", layout="wide")


# 캐싱을 통해 매번 Github API를 호출하지 않도록 최적화 (데이터 읽기용)
@st.cache_data(ttl=60)
def load_data_from_github(file_name):
    try:
        g = Github(st.secrets["github"]["token"])
        repo = g.get_repo(st.secrets["github"]["repo_name"])
        contents = repo.get_contents(file_name)
        decoded = contents.decoded_content.decode("utf-8")
        return pd.read_csv(StringIO(decoded))
    except Exception as e:
        st.error(f"데이터 로드 실패: {e}")
        return pd.DataFrame()


# Github에 데이터 업데이트 (쓰기용 - 커밋 발생)
def save_data_to_github(df, file_name, message):
    try:
        g = Github(st.secrets["github"]["token"])
        repo = g.get_repo(st.secrets["github"]["repo_name"])
        contents = repo.get_contents(file_name)

        # DataFrame을 CSV 문자열로 변환
        csv_buffer = StringIO()
        df.to_csv(csv_buffer, index=False)
        new_content = csv_buffer.getvalue()

        # 파일 업데이트 (Commit)
        repo.update_file(contents.path, message, new_content, contents.sha)
        st.cache_data.clear()  # 캐시 초기화하여 변경사항 즉시 반영
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
# 3. 사용자 구분 및 보안 (Constraint 8, 8-1)
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
# 4. 메뉴 구성 (Constraint 5, 6, 7)
# ---------------------------------------------------------
menu_options = ["주문 청구", "현재 재고"]
if is_admin:
    menu_options += ["입출고 입력", "거래 기록", "알림", "리포트 및 분석"]

choice = st.title("📚 인하대 출판부 재고 관리 시스템")
selected_menu = st.sidebar.selectbox("메뉴 선택", menu_options)

# ---------------------------------------------------------
# 5. 기능 구현
# ---------------------------------------------------------

# === [1] 현재 재고 (Constraint 11) ===
# 내/외부 모두 접근 가능
if selected_menu == "현재 재고":
    st.header("📦 현재 재고 조회")

    search_query = st.text_input("책 이름 또는 ISBN 검색")

    if search_query:
        # 책 이름이나 ISBN에 검색어가 포함된 행 필터링
        result = df_inventory[
            df_inventory['책 이름'].str.contains(search_query) |
            df_inventory['ISBN'].str.contains(search_query)
            ]
    else:
        result = df_inventory

    # 외부 이용자에게 안전재고는 보여주지 않을 수도 있으나, 요구사항에 명시되지 않았으므로 전체 출력
    st.dataframe(result[['책 이름', 'ISBN', '가격', '현재 수량']], use_container_width=True)


# === [2] 주문 청구 (Constraint 9) ===
# 내/외부 모두 접근 가능
elif selected_menu == "주문 청구":
    st.header("📝 도서 주문 청구")

    with st.form("order_form"):
        # 9-1: 책 이름 선택 (Dropdown)
        book_list = df_inventory['책 이름'].tolist()
        client_name = st.text_input("거래처/주문자명")
        selected_book = st.selectbox("책 이름 선택", book_list)
        order_qty = st.number_input("주문 수량", min_value=1, value=10)

        submitted = st.form_submit_button("주문하기")

        if submitted:
            if not client_name:
                st.error("거래처/주문자명을 입력해주세요.")
            else:
                # 9-2: 알림 항목(orders.csv)에 저장
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


# === [3] 입출고 입력 (Constraint 10) - 관리자 전용 ===
elif selected_menu == "입출고 입력" and is_admin:
    st.header("🚚 입출고 관리")

    with st.form("transaction_form"):
        tx_type = st.radio("거래 유형", ["입고", "출고", "파손", "반품"])
        client_name = st.text_input("거래처 (파손 시 생략 가능)")

        book_list = df_inventory['책 이름'].tolist()
        selected_book = st.selectbox("책 이름", book_list)
        qty = st.number_input("수량", min_value=1)

        submitted = st.form_submit_button("입력 완료")

        if submitted:
            # 파손이 아닌데 거래처가 없으면 경고
            if tx_type != "파손" and not client_name:
                st.error("거래처를 입력해주세요.")
            else:
                # 데이터 처리
                current_book_info = df_inventory[df_inventory['책 이름'] == selected_book].iloc[0]
                current_qty = int(current_book_info['현재 수량'])
                price = int(current_book_info['가격'])

                new_qty = current_qty

                # 수량 계산 로직 (Constraint 12-2, 12-3)
                if tx_type in ["입고", "반품"]:
                    new_qty += qty
                elif tx_type in ["출고", "파손"]:
                    if current_qty < qty:
                        st.error("재고가 부족합니다.")
                        st.stop()
                    new_qty -= qty

                # 1. 재고 업데이트
                df_inventory.loc[df_inventory['책 이름'] == selected_book, '현재 수량'] = new_qty

                # 2. 거래 기록 생성 (Constraint 12)
                new_tx = pd.DataFrame({
                    "일시": [datetime.now().strftime("%Y-%m-%d %H:%M:%S")],
                    "거래처": [client_name if client_name else "N/A"],
                    "책 이름": [selected_book],
                    "수량": [qty],
                    "가격": [price],
                    "유형": [tx_type]
                })

                updated_tx = pd.concat([df_transactions, new_tx], ignore_index=True)

                # Github에 저장 (Batch commit이 안되므로 순차 저장)
                save_inventory = save_data_to_github(df_inventory, "inventory.csv",
                                                     f"Update Inventory: {selected_book}")
                save_tx = save_data_to_github(updated_tx, "transactions.csv", f"Add Tx: {tx_type} - {selected_book}")

                if save_inventory and save_tx:
                    st.success(f"{tx_type} 처리 완료! (현재 재고: {new_qty}권)")


# === [4] 거래 기록 (Constraint 12) - 관리자 전용 ===
elif selected_menu == "거래 기록" and is_admin:
    st.header("📋 전체 거래 내역")

    # 12-1: 최근 거래가 위로 오도록 정렬
    if not df_transactions.empty:
        df_sorted = df_transactions.sort_values(by="일시", ascending=False)
        st.dataframe(df_sorted, use_container_width=True)
    else:
        st.info("거래 기록이 없습니다.")


# === [5] 알림 (Constraint 13) - 관리자 전용 ===
elif selected_menu == "알림" and is_admin:
    st.header("🔔 알림 센터")

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("1. 신규 주문 요청")  # Constraint 13-1
        pending_orders = df_orders[df_orders['상태'] == '미처리']
        if not pending_orders.empty:
            for idx, row in pending_orders.iterrows():
                st.warning(f"📢 **{row['거래처']}**에서 **{row['책 이름']}** {row['주문 수량']}권 주문 요청")
        else:
            st.success("신규 주문이 없습니다.")

    with col2:
        st.subheader("2. 안전 재고 미달 알림")  # Constraint 13-2
        # 재고 수량이 안전 재고 이하인 경우 찾기
        # 주의: 문자열로 읽힐 수 있으므로 숫자로 변환
        df_inventory['현재 수량'] = pd.to_numeric(df_inventory['현재 수량'])
        df_inventory['안전 재고'] = pd.to_numeric(df_inventory['안전 재고'])

        low_stock = df_inventory[df_inventory['현재 수량'] <= df_inventory['안전 재고']]

        if not low_stock.empty:
            for idx, row in low_stock.iterrows():
                st.error(f"🚨 **{row['책 이름']}** 재고 부족! (현재: {row['현재 수량']} / 안전선: {row['안전 재고']})")
        else:
            st.success("모든 재고가 안전합니다.")


# === [6] 리포트 및 분석 (Constraint 14) - 관리자 전용 ===
elif selected_menu == "리포트 및 분석" and is_admin:
    st.header("📈 데이터 분석 리포트")

    # 데이터 전처리
    df_transactions['일시'] = pd.to_datetime(df_transactions['일시'])
    df_inventory['현재 수량'] = pd.to_numeric(df_inventory['현재 수량'])
    df_inventory['가격'] = pd.to_numeric(df_inventory['가격'])

    tab1, tab2, tab3 = st.tabs(["월간 판매량", "재고 자산 평가", "거래처별 반품률"])

    with tab1:  # 14-1 월간 판매량
        st.subheader("월별 도서 판매 추이")
        # '출고' 데이터만 필터링
        sales_df = df_transactions[df_transactions['유형'] == '출고'].copy()
        if not sales_df.empty:
            sales_df['월'] = sales_df['일시'].dt.strftime('%Y-%m')
            monthly_sales = sales_df.groupby(['월', '책 이름'])['수량'].sum().reset_index()

            fig = px.bar(monthly_sales, x='월', y='수량', color='책 이름', barmode='group')
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("출고 기록이 없어 그래프를 그릴 수 없습니다.")

    with tab2:  # 14-2 재고 자산 평가
        st.subheader("현재 재고 총 가치")
        total_value = (df_inventory['현재 수량'] * df_inventory['가격']).sum()
        st.metric(label="총 재고 자산 가치", value=f"{total_value:,.0f} 원")

        # 상세 테이블
        df_inventory['자산 가치'] = df_inventory['현재 수량'] * df_inventory['가격']
        st.dataframe(df_inventory[['책 이름', '현재 수량', '가격', '자산 가치']])

    with tab3:  # 14-3 거래처별 반품률
        st.subheader("거래처별 반품률 분석")
        # 거래처별 전체 거래 수(파손 제외)와 반품 수 계산
        tx_valid = df_transactions[df_transactions['거래처'] != 'N/A'].copy()

        if not tx_valid.empty:
            # 거래처별 '출고' 수량 합계 (판매량)
            sales_by_client = tx_valid[tx_valid['유형'] == '출고'].groupby('거래처')['수량'].sum()
            # 거래처별 '반품' 수량 합계
            returns_by_client = tx_valid[tx_valid['유형'] == '반품'].groupby('거래처')['수량'].sum()

            # DataFrame 합치기
            analysis_df = pd.DataFrame({'총 판매량': sales_by_client, '총 반품량': returns_by_client}).fillna(0)

            # 반품률 계산 (반품 / (판매 + 반품)) * 100
            # *반품률 정의는 조직마다 다르나 여기서는 (반품수량 / 전체 처리수량)으로 가정하거나 (반품/판매)로 할 수 있음.
            # 여기서는 (반품량 / 판매량)으로 계산하되 판매량이 0이면 0처리

            analysis_df['반품률(%)'] = (analysis_df['총 반품량'] / analysis_df['총 판매량']) * 100
            analysis_df['반품률(%)'] = analysis_df['반품률(%)'].fillna(0).round(2)

            st.dataframe(analysis_df)
        else:
            st.info("분석할 거래 데이터가 충분하지 않습니다.")