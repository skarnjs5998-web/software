import streamlit as st
import pandas as pd
from github import Github
from io import StringIO
from datetime import datetime
import pytz

# ---------------------------------------------------------
# 1. 설정 및 Github 연결 함수
# ---------------------------------------------------------
st.set_page_config(page_title="인하대 출판부 재고 관리", layout="wide")

# [수정 1] 한국 시간 구하는 함수 정의
def get_korea_time():
    utc_now = datetime.now(pytz.utc)
    korea_timezone = pytz.timezone('Asia/Seoul')
    korea_now = utc_now.astimezone(korea_timezone)
    return korea_now.strftime("%Y-%m-%d %H:%M:%S")

@st.cache_data(ttl=60)
def load_data_from_github(file_name):
    try:
        g = Github(st.secrets["github"]["token"])
        repo = g.get_repo(st.secrets["github"]["repo_name"])
        contents = repo.get_contents(file_name)
        
        # 1. BOM 제거 (utf-8-sig)
        decoded = contents.decoded_content.decode("utf-8-sig")
        df = pd.read_csv(StringIO(decoded))
        
        # 2. 기본 공백 제거
        df.columns = df.columns.str.strip().str.replace("\xa0", " ")
        
        # 3. 컬럼 이름 정규화
        rename_map = {}
        for col in df.columns:
            clean_col = col.replace(" ", "") 
            if "책이름" in clean_col:
                rename_map[col] = "책 이름"
            elif "현재수량" in clean_col:
                rename_map[col] = "현재 수량"
            elif "안전재고" in clean_col:
                rename_map[col] = "안전 재고"
            elif "ISBN" in clean_col:
                rename_map[col] = "ISBN"
        
        if rename_map:
            df = df.rename(columns=rename_map)
            
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
    menu_options += ["입출고 입력", "거래 기록", "알림", "수익 분석"]

choice = st.title("📚 인하대 출판부 재고 관리 시스템")
selected_menu = st.sidebar.selectbox("메뉴 선택", menu_options)

# ---------------------------------------------------------
# 5. 기능 구현
# ---------------------------------------------------------

# === [1] 현재 재고 ===
if selected_menu == "현재 재고":
    st.subheader("🔍 현재 재고 현황")

    col1, col2 = st.columns([3, 1])
    with col1:
        search_term = st.text_input("검색 (책 이름 또는 ISBN)", placeholder="검색어를 입력하세요...")

    if search_term:
        mask = df_inventory['책 이름'].astype(str).str.contains(search_term) | df_inventory['ISBN'].astype(str).str.contains(search_term)
        result = df_inventory[mask]
    else:
        result = df_inventory

    config = {}
    if "가격" in result.columns:
        config["가격"] = st.column_config.NumberColumn(format="%d원")
    if "현재 수량" in result.columns:
        config["현재 수량"] = st.column_config.NumberColumn(format="%d권")

    st.dataframe(
        result,
        column_config=config,
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
                        "일시": [get_korea_time()],
                        "거래처": [client_name],
                        "책 이름": [selected_book],
                        "주문 수량": [order_qty],
                        "상태": ["미처리"]
                    })
                    updated_orders = pd.concat([df_orders, new_order], ignore_index=True)
                    if save_data_to_github(updated_orders, "orders.csv", f"Order request: {client_name}"):
                        st.success(f"주문이 접수되었습니다.\n\n거래처: {client_name}, 책: {selected_book}, 수량: {order_qty}")
        else:
            st.error(f"'책 이름' 컬럼을 찾을 수 없습니다.")

# === [3] 입출고 입력 (관리자) ===
elif selected_menu == "입출고 입력" and is_admin:
    st.header("🚚 입출고 관리")
    
    required_cols = ['책 이름', '현재 수량', '가격']
    missing_cols = [col for col in required_cols if col not in df_inventory.columns]
    
    if missing_cols:
         st.error(f"데이터 오류: 다음 컬럼을 찾을 수 없습니다 -> {missing_cols}")
    else:
        with st.form("transaction_form"):
            # [수정 3] 취소(증가), 취소(감소) 항목 추가
            tx_type = st.radio("거래 유형", ["입고", "출고", "파손", "반품", "취소(증가)", "취소(감소)"])
            st.caption("'취소(증가)': 재고 증가 (출고 취소 시 사용) | '취소(감소)': 재고 감소 (입고 취소 시 사용)")
            
            client_name = st.text_input("거래처 (파손 시 생략 가능)")
            book_list = df_inventory['책 이름'].tolist()
            selected_book = st.selectbox("책 이름", book_list)
            qty = st.number_input("수량", min_value=1)
            
            submitted = st.form_submit_button("입력 완료")
            
            if submitted:
                if "파손" not in tx_type and not client_name:
                    st.error("거래처를 입력해주세요.")
                else:
                    try:
                        current_book_info = df_inventory[df_inventory['책 이름'] == selected_book].iloc[0]
                        current_qty = int(current_book_info['현재 수량'])
                        price = int(current_book_info['가격'])
                        
                        new_qty = current_qty
                        
                    
                        
                        if tx_type in ["입고", "반품", "취소(증가)"]:
                            new_qty += qty
                            
                        # 감소 그룹: 출고, 파손, 취소(감소)
                        elif tx_type in ["출고", "파손", "취소(감소)"]:
                            if current_qty < qty:
                                st.error("재고가 부족합니다.")
                                st.stop()
                            new_qty -= qty
                        
                        df_inventory.loc[df_inventory['책 이름'] == selected_book, '현재 수량'] = new_qty
                        
                        new_tx = pd.DataFrame({
                            "일시": [get_korea_time()], # [수정 1] 한국 시간 적용
                            "거래처": [client_name if client_name else "N/A"],
                            "책 이름": [selected_book],
                            "수량": [qty],
                            "가격": [price],
                            "유형": [tx_type]
                        })
                        
                        updated_tx = pd.concat([df_transactions, new_tx], ignore_index=True)
                        
                        save_inventory = save_data_to_github(df_inventory, "inventory.csv", f"Update Inventory: {selected_book}")
                        save_tx = save_data_to_github(updated_tx, "transactions.csv", f"Add Tx: {tx_type} - {selected_book}")
                        
                        if save_inventory and save_tx:
                            st.success(f"{tx_type} 처리 완료! (현재 재고: {new_qty}권)")
                            
                    except Exception as e:
                        st.error(f"처리 중 오류 발생: {e}")

# === [4] 거래 기록 (관리자) ===
elif selected_menu == "거래 기록" and is_admin:
    st.header("📋 전체 거래 내역")
    
    
    with st.expander("🚨 잘못 입력한 거래 취소 및 되돌리기 (클릭하여 열기)"):
        st.caption("주의: 이 기능은 선택한 거래 기록을 삭제하고, 재고 수량을 해당 거래 이전으로 되돌립니다.")
        
        if not df_transactions.empty:
            recent_tx = df_transactions.sort_values(by="일시", ascending=False).head(20).copy()
            recent_tx['display_text'] = (
                recent_tx['일시'].astype(str) + " | " + 
                recent_tx['유형'] + " | " + 
                recent_tx['책 이름'] + " (" + 
                recent_tx['수량'].astype(str) + "권)"
            )
            
            selected_cancel_tx = st.selectbox(
                "취소할 거래를 선택하세요 (최근 20건)", 
                recent_tx['display_text'].tolist()
            )
            
            if st.button("선택한 거래 취소 및 원상복구"):
                target_tx = recent_tx[recent_tx['display_text'] == selected_cancel_tx].iloc[0]
                target_book = target_tx['책 이름']
                target_qty = int(target_tx['수량'])
                target_type = target_tx['유형']
                
                revert_qty = 0
                # 증가 그룹 취소 -> 감소
                if target_type in ["입고", "반품", "취소(증가)"]:
                    revert_qty = -target_qty
                # 감소 그룹 취소 -> 증가
                elif target_type in ["출고", "파손", "취소(감소)"]:
                    revert_qty = target_qty
                
                if target_book in df_inventory['책 이름'].values:
                    current_stock = int(df_inventory.loc[df_inventory['책 이름'] == target_book, '현재 수량'].values[0])
                    new_stock_after_cancel = current_stock + revert_qty
                    
                    if new_stock_after_cancel < 0:
                        st.error(f"취소 불가능: 이 거래를 취소하면 재고가 음수({new_stock_after_cancel})가 됩니다.")
                    else:
                        df_inventory.loc[df_inventory['책 이름'] == target_book, '현재 수량'] = new_stock_after_cancel
                        
                        original_index = df_transactions[
                            (df_transactions['일시'] == target_tx['일시']) & 
                            (df_transactions['책 이름'] == target_book) &
                            (df_transactions['유형'] == target_type) &
                            (df_transactions['수량'] == target_qty)
                        ].index
                        
                        if not original_index.empty:
                            df_transactions = df_transactions.drop(original_index[0])
                            
                            save_inv = save_data_to_github(df_inventory, "inventory.csv", f"Revert Tx: {target_book}")
                            save_tx = save_data_to_github(df_transactions, "transactions.csv", f"Cancel Tx: {selected_cancel_tx}")
                            
                            if save_inv and save_tx:
                                st.success(f"거래가 취소되었습니다. 재고가 {current_stock} -> {new_stock_after_cancel} 권으로 복구되었습니다.")
                                st.rerun()
                        else:
                            st.error("원본 데이터를 찾을 수 없어 삭제하지 못했습니다.")
                else:
                    st.error(f"'{target_book}' 책을 재고 목록에서 찾을 수 없습니다.")
        else:
            st.info("취소할 거래 기록이 없습니다.")

    # 거래 기록 테이블 표시
    if not df_transactions.empty:
        df_sorted = df_transactions.sort_values(by="일시", ascending=False)
        # [수정 2] 가장 좌측의 인덱스 번호 숨기기 (hide_index=True)
        st.dataframe(df_sorted, use_container_width=True, hide_index=True)
    else:
        st.info("거래 기록이 없습니다.")

# === [5] 알림 (관리자) ===
elif selected_menu == "알림" and is_admin:
    st.header("🔔 알림 센터")
    
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("1. 신규 주문 요청")
        # '미처리' 상태인 주문만 가져오기
        if not df_orders.empty and '상태' in df_orders.columns:
            # 인덱스를 유지하기 위해 reset_index를 하지 않음
            pending_orders = df_orders[df_orders['상태'] == '미처리']
            
            if not pending_orders.empty:
                for idx, row in pending_orders.iterrows():
                    # 각 주문마다 박스를 만들고 버튼 추가
                    with st.container(border=True):
                        st.write(f"📢 **{row['거래처']}** - **{row['책 이름']}** ({row['주문 수량']}권)")
                        st.caption(f"요청 일시: {row['일시']}")
                        
                        # [수정 4] 처리 완료 버튼 추가
                        # 고유한 key를 위해 idx 사용
                        if st.button("처리 완료", key=f"btn_complete_{idx}"):
                            # 원본 데이터프레임(df_orders)에서 해당 행의 상태를 '처리'로 변경
                            df_orders.loc[idx, '상태'] = "처리"
                            
                            if save_data_to_github(df_orders, "orders.csv", f"Order Processed: {row['거래처']}"):
                                st.success("처리 상태가 변경되었습니다.")
                                st.rerun() # 즉시 새로고침하여 목록에서 제거
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
            st.error(f"재고 체크 불가: 컬럼 오류")

# === [6] 수익 분석 (날짜 파싱 강화) ===
elif selected_menu == "수익 분석" and is_admin:
    st.header("💰 월간 수익 및 비용 분석")
    
    if df_transactions.empty:
        st.info("거래 기록이 없어 분석할 수 없습니다.")
    else:
        df_analysis = df_transactions.copy()
        
        df_analysis['일시'] = df_analysis['일시'].astype(str).str.replace('.', '-', regex=False).str.strip()
        
        try:
            df_analysis['일시'] = pd.to_datetime(df_analysis['일시'], format='mixed', errors='coerce')
        except:
            df_analysis['일시'] = pd.to_datetime(df_analysis['일시'], errors='coerce')
        
        if df_analysis['일시'].isnull().any():
            invalid_count = df_analysis['일시'].isnull().sum()
            st.warning(f"⚠️ 여전히 형식을 알 수 없는 날짜 데이터 {invalid_count}건이 있습니다.")
            df_analysis = df_analysis.dropna(subset=['일시'])
            
        if df_analysis.empty:
            st.error("유효한 날짜를 가진 거래 기록이 없습니다.")
        else:
            df_analysis['월'] = df_analysis['일시'].dt.strftime('%Y-%m')
            
            all_months = sorted(df_analysis['월'].unique().tolist(), reverse=True)
            selected_month = st.selectbox("분석할 월을 선택하세요", all_months)
            
            monthly_data = df_analysis[df_analysis['월'] == selected_month]
            
            if monthly_data.empty:
                st.warning("선택한 달에 데이터가 없습니다.")
            else:
                monthly_data['총액'] = monthly_data['수량'] * monthly_data['가격']
                summary = monthly_data.groupby('유형')['총액'].sum()
                
                # [수정 3] 취소 항목들도 계산에 반영
                total_out = summary.get('출고', 0) + summary.get('취소(감소)', 0) # 나간 돈
                total_in = summary.get('입고', 0) + summary.get('취소(증가)', 0) # 들어온 돈 (비용) -> *주의: 취소(증가)는 재고가 늘어난 것이므로 비용으로 볼 수 있음(반품 취소 등) 혹은 문맥에 따라 다름. 여기선 단순 합산.
                total_return = summary.get('반품', 0)
                total_damage = summary.get('파손', 0)
                
                # 로직 일관성:
                # 수익 = (출고 - 반품) + (취소(감소)는 출고와 같음)
                # *단, 취소(증가)는 '출고 취소'의 의미라면 수익을 줄여야 하고, '입고'의 의미라면 비용을 늘려야 함.
                # 사용자의 정의: "취소(증가)는 출고를 잘못 입력했을 경우" -> 즉, 출고된 걸 다시 가져옴 -> 수익 취소? or 재고 자산 증가?
                # 사용자의 정의: "취소(감소)는 입고를 잘못 입력했을 경우" -> 즉, 입고된 걸 다시 뺌.
                
                # 여기서는 '유형'에 따라 재고가 움직인 대로 단순히 합산합니다.
                # 수익 관련: 출고(+), 취소(감소)(+), 반품(-) 
                revenue = (summary.get('출고', 0) + summary.get('취소(감소)', 0)) - summary.get('반품', 0)
                
                # 비용 관련: 입고(+), 취소(증가)(+), 파손(+)
                cost = (summary.get('입고', 0) + summary.get('취소(증가)', 0)) + summary.get('파손', 0)
                
                net_profit = revenue - cost
                
                st.markdown("---")
                c1, c2, c3 = st.columns(3)
                
                with c1:
                    st.metric(label="총 수익 (Revenue)", value=f"{revenue:,.0f} 원", 
                              help="(출고 + 취소(감소)) - 반품")
                with c2:
                    st.metric(label="총 비용 (Cost)", value=f"{cost:,.0f} 원", 
                              help="(입고 + 취소(증가)) + 파손")
                with c3:
                    st.metric(label="순이익 (Net Profit)", value=f"{net_profit:,.0f} 원", 
                              delta=f"{net_profit:,.0f} 원",
                              help="수익 - 비용")
                st.markdown("---")
                
                with st.expander("📊 상세 거래 내역 보기"):
                    st.dataframe(monthly_data[['일시', '거래처', '책 이름', '유형', '수량', '가격', '총액']], 
                                 use_container_width=True, hide_index=True)

