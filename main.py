# 파일명: data_export.py
# 일별 OHLC 추출기 v3 — 견고성 강화 (개별 티커 fetch + 폴백 + 에러 표시)
# 독립 앱. Secrets 불필요. 모바일 친화. CSV 다운로드.
#
# v3 변경점:
#   - Close 만 뽑던 것을 OHLC(Open/High/Low/Close) 전체로 확장
#   - CSV 컬럼: Date, TICKER_Open, TICKER_High, TICKER_Low, TICKER_Close ...
#   - 기본 티커/프리셋을 QQQ,TQQQ,SOXL 로 교체
#
# ★ 배포 시 같은 레포에 requirements.txt 가 반드시 있어야 합니다(아래 4줄):
#     streamlit
#     yfinance
#     pandas
#     numpy
#   (yfinance 가 불안정하면 'yfinance==0.2.54' 처럼 버전을 고정하세요.)
import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime
import time

st.set_page_config(page_title="일별 OHLC 추출기 v3", page_icon="📥", layout="wide")
st.title("📥 일별 OHLC 추출기 v3")
st.caption("티커 → 데이터 가져오기 → CSV 다운로드. 개별 티커 fetch로 한 종목이 실패해도 나머지는 살립니다. (OHLC 전체 추출)")

# yfinance 는 런타임에 import (실패해도 앱이 죽지 않고 안내 메시지 표시)
try:
    import yfinance as yf
    YF_OK = True
    YF_ERR = ""
except Exception as e:
    YF_OK = False
    YF_ERR = str(e)

if not YF_OK:
    st.error("yfinance 를 불러오지 못했습니다. 레포의 requirements.txt 에 yfinance 가 있는지 확인하세요.")
    st.code("streamlit\nyfinance\npandas\nnumpy", language="text")
    st.caption(f"세부 오류: {YF_ERR}")
    st.stop()

PRESETS = {
    "Dongpa 핵심 (QQQ·TQQQ·SOXL)": "QQQ,TQQQ,SOXL",
    "매니지드 퓨처스 비교 (KMLM·DBMF·CTA)": "KMLM,DBMF,CTA,SPY",
    "비주식 분산자산 (채권·금·원자재·달러)": "TLT,IEF,GLD,DBC,UUP,SPY,QQQ",
}
DESC = {
    "QQQ": "나스닥100", "TQQQ": "나스닥100 3배", "SOXL": "반도체 3배", "SOXX": "반도체 지수",
    "SPY": "S&P500",
    "KMLM": "매니지드퓨처스(룰기반,투명,11시장 롱숏)",
    "DBMF": "매니지드퓨처스(헤지펀드 복제,최대 유동성)",
    "CTA":  "매니지드퓨처스(내부 레버리지,변동성 큼)",
    "TLT": "美 장기국채 20년+", "IEF": "美 중기국채 7-10년", "GLD": "금",
    "DBC": "원자재 바스켓", "UUP": "달러 강세", "UDN": "달러 약세",
    "TBF": "美 장기국채 인버스(-1x)",
}

OHLC = ["Open", "High", "Low", "Close"]

st.markdown("**빠른 선택**")
pcols = st.columns(len(PRESETS))
if "tickers_str" not in st.session_state:
    st.session_state["tickers_str"] = PRESETS["Dongpa 핵심 (QQQ·TQQQ·SOXL)"]
for i, (label, val) in enumerate(PRESETS.items()):
    if pcols[i].button(label, use_container_width=True):
        st.session_state["tickers_str"] = val

tickers_str = st.text_input("티커 (쉼표로 구분)", key="tickers_str")
c1, c2 = st.columns(2)
start_d = c1.date_input("시작일", value=datetime(2005, 1, 1), min_value=datetime(1990, 1, 1))
end_d   = c2.date_input("종료일", value=datetime.today())
adjust  = st.checkbox("배당·분할 반영 OHLC(총수익, 권장)", value=True,
                      help="채권/배당 ETF는 총수익 기준이 정확합니다. OHLC 전체가 동일 배율로 조정됩니다.")

def _extract_ohlc(frame):
    """OHLC 컬럼만 골라 숫자형 DataFrame 으로 반환. 없으면 None."""
    out = pd.DataFrame(index=frame.index)
    for col in OHLC:
        if col in frame.columns:
            out[col] = pd.to_numeric(frame[col], errors="coerce")
    out = out.dropna(how="all")
    if len(out) > 0 and "Close" in out.columns:
        return out
    return None

def fetch_one(ticker, start, end, adjust):
    """단일 티커 OHLC DataFrame 반환(실패 시 None). download -> history 폴백."""
    for attempt in range(2):
        try:
            d = yf.download(ticker, start=start, end=end, auto_adjust=adjust,
                            progress=False, threads=False)
            if d is not None and len(d) > 0:
                if isinstance(d.columns, pd.MultiIndex):
                    lvl0 = d.columns.get_level_values(0)
                    # 첫 레벨이 필드명(Open/High/Low/Close)이면 두번째(티커) 레벨 제거
                    if "Close" in lvl0:
                        d = d.droplevel(1, axis=1)
                    else:
                        d = d.droplevel(0, axis=1)
                out = _extract_ohlc(d)
                if out is not None:
                    return out
        except Exception:
            pass
        try:
            h = yf.Ticker(ticker).history(start=start, end=end, auto_adjust=adjust)
            if h is not None and len(h) > 0:
                out = _extract_ohlc(h)
                if out is not None:
                    return out
        except Exception:
            pass
        time.sleep(1)
    return None

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_all(tickers, start, end, adjust):
    frames, failed = {}, []
    for t in tickers:
        df1 = fetch_one(t, start, end, adjust)
        if df1 is None:
            failed.append(t)
        else:
            df1.index = pd.to_datetime(df1.index)
            try:
                df1.index = df1.index.tz_localize(None)
            except (TypeError, AttributeError):
                pass
            frames[t] = df1
    if not frames:
        return pd.DataFrame(), failed
    df = pd.concat(frames, axis=1)
    # MultiIndex (ticker, field) -> "TICKER_Field"
    df.columns = [f"{tk}_{field}" for tk, field in df.columns]
    df = df.sort_index()
    df.index.name = "Date"
    return df, failed

if st.button("🚀 데이터 가져오기", type="primary"):
    tickers = [t.strip().upper() for t in tickers_str.split(",") if t.strip()]
    if not tickers:
        st.error("티커를 하나 이상 입력하세요.")
    else:
        with st.spinner(f"{len(tickers)}개 티커를 개별로 가져오는 중..."):
            try:
                data, failed = fetch_all(tickers, str(start_d), str(end_d), adjust)
                st.session_state["data"] = data
                st.session_state["failed"] = failed
                st.session_state["adjust_used"] = adjust
            except Exception as e:
                st.error(f"가져오기 중 오류: {e}")
                st.info("잠시 후 다시 시도하거나, requirements.txt 의 yfinance 버전을 고정해 보세요.")

if "data" in st.session_state and not st.session_state["data"].empty:
    data = st.session_state["data"]
    failed = st.session_state.get("failed", [])
    adj_used = st.session_state.get("adjust_used", True)

    close_cols = [c for c in data.columns if c.endswith("_Close")]
    tickers_ok = [c[:-len("_Close")] for c in close_cols]

    if failed:
        st.warning(f"⚠️ 못 가져온 티커(철자/상장/거래정지 확인): {', '.join(failed)}")
    st.success(f"✅ {len(tickers_ok)}개 종목 · {len(data):,}행 · OHLC "
               f"({data.index.min().date()} ~ {data.index.max().date()}) "
               f"· {'배당반영(총수익)' if adj_used else '단순 가격'}")

    st.markdown("#### 📋 자산별 데이터 범위")
    cov = []
    for cc, tk in zip(close_cols, tickers_ok):
        s = data[cc].dropna()
        cov.append({"티커": tk, "설명": DESC.get(tk, "-"),
                    "시작": s.index.min().date() if len(s) else "-",
                    "종료": s.index.max().date() if len(s) else "-",
                    "일수": int(len(s))})
    st.dataframe(pd.DataFrame(cov), use_container_width=True, hide_index=True)

    st.markdown("#### 📈 정규화 추이 (각 자산 종가 첫 유효일 = 100)")
    try:
        norm = pd.DataFrame(index=data.index)
        for cc, tk in zip(close_cols, tickers_ok):
            s = data[cc]
            fv_idx = s.first_valid_index()
            if fv_idx is not None and s.loc[fv_idx] > 0:
                norm[tk] = s / s.loc[fv_idx] * 100
        st.line_chart(norm)
    except Exception:
        st.caption("차트 생략(데이터 확인).")

    st.markdown("#### 🔎 최근 5행 (OHLC)")
    st.dataframe(data.tail(5).round(4), use_container_width=True)

    out = data.reset_index()
    out["Date"] = pd.to_datetime(out["Date"]).dt.strftime("%Y-%m-%d")
    csv_bytes = out.round(6).to_csv(index=False).encode("utf-8-sig")
    st.download_button("⬇️ CSV 다운로드 (OHLC)", data=csv_bytes,
                       file_name=f"daily_ohlc_{datetime.today():%Y%m%d}.csv",
                       mime="text/csv", type="primary", use_container_width=True)
    st.caption("컬럼 형식: Date, TICKER_Open, TICKER_High, TICKER_Low, TICKER_Close ... "
               "내려받은 CSV를 분석 대화에 업로드하세요.")
else:
    st.info("프리셋을 누르거나 티커를 입력하고 데이터 가져오기를 누르세요. "
            "기본값은 QQQ·TQQQ·SOXL 입니다.")

with st.expander("⚙️ 배포가 자꾸 죽으면 (requirements.txt)"):
    st.markdown("레포 루트에 아래 내용의 **requirements.txt** 가 있어야 합니다:")
    st.code("streamlit\nyfinance\npandas\nnumpy", language="text")
    st.markdown("그래도 불안정하면 yfinance 버전을 고정하세요(예시):")
    st.code("streamlit\nyfinance==0.2.54\npandas\nnumpy", language="text")
