# 파일명: fetch_minute.py
# ============================================================================
#  Alpaca 분봉 다운로더 — SOXL 1분봉 전체 이력 CSV 저장
# ----------------------------------------------------------------------------
#  ★ 무료 계정으로 SIP(전체 시장) 과거 데이터를 받을 수 있다.
#    IEX 제한은 '실시간'에만 걸리고, 과거 조회는 end가 15분 이상 지났으면
#    구독 없이 SIP를 쓸 수 있다. 백테스트 용도로는 제약이 없다.
#
#  준비: alpaca.markets 가입 → Paper 계정 → API Key 발급 (입금 불필요)
#
#  실행:
#    set ALPACA_KEY=...
#    set ALPACA_SECRET=...
#    python fetch_minute.py                 (2016~현재, 1분봉)
#    python fetch_minute.py 2020-01-01      (시작일 지정)
#    python fetch_minute.py 2020-01-01 5Min (5분봉)
#
#  출력: SOXL_1Min.csv  (datetime, open, high, low, close, volume)
#        · 타임존은 미국 동부(ET)로 변환해 저장
#        · adjustment=all 로 분할·배당 조정 적용 (SOXL은 역분할 이력 있음)
# ============================================================================
import os
import sys
import time
import requests
import pandas as pd

KEY    = os.environ.get("ALPACA_KEY", "")
SECRET = os.environ.get("ALPACA_SECRET", "")

SYMBOL = "SOXL"
BASE   = "https://data.alpaca.markets/v2/stocks/bars"
LIMIT  = 10000          # 요청당 최대 바 수


def fetch(symbol, start, end, timeframe="1Min"):
    """페이지네이션으로 전체 구간을 받아온다."""
    if not KEY or not SECRET:
        print("🚨 환경변수 ALPACA_KEY / ALPACA_SECRET 이 필요합니다.")
        sys.exit(1)

    headers = {"APCA-API-KEY-ID": KEY, "APCA-API-SECRET-KEY": SECRET}
    rows, token, page = [], None, 0

    while True:
        params = {
            "symbols": symbol,
            "timeframe": timeframe,
            "start": start,
            "end": end,
            "limit": LIMIT,
            "adjustment": "all",   # 분할·배당 조정 (SOXL 역분할 대응)
            "feed": "sip",         # 전체 시장. 과거 조회는 무료로 가능
            "sort": "asc",
        }
        if token:
            params["page_token"] = token

        for attempt in range(5):
            try:
                r = requests.get(BASE, headers=headers, params=params, timeout=60)
                if r.status_code == 429:
                    print("   rate limit — 30초 대기")
                    time.sleep(30)
                    continue
                if r.status_code == 403:
                    print(f"🚨 403: {r.text[:300]}")
                    print("   feed=sip 이 거절되면 feed=iex 로 바꿔 재시도하세요.")
                    sys.exit(1)
                r.raise_for_status()
                break
            except Exception as e:
                print(f"   재시도 {attempt+1}/5: {e}")
                time.sleep(5)
        else:
            print("🚨 요청 실패")
            sys.exit(1)

        d = r.json()
        bars = (d.get("bars") or {}).get(symbol, [])
        rows.extend(bars)
        token = d.get("next_page_token")
        page += 1
        if bars:
            print(f"  page {page:>3}  누적 {len(rows):>8,}개  "
                  f"(~{bars[-1]['t'][:10]})")
        if not token:
            break

    return rows


def main():
    start = sys.argv[1] if len(sys.argv) > 1 else "2016-01-01"
    tf    = sys.argv[2] if len(sys.argv) > 2 else "1Min"
    # end는 넉넉히 과거로 — 15분 규칙을 안전하게 피한다
    end = (pd.Timestamp.utcnow() - pd.Timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")

    print(f"■ {SYMBOL} {tf} 다운로드")
    print(f"  기간 {start} ~ {end[:10]}\n")

    rows = fetch(SYMBOL, start, end, tf)
    if not rows:
        print("🚨 데이터가 없습니다.")
        return

    df = pd.DataFrame(rows)
    df = df.rename(columns={"t": "datetime", "o": "open", "h": "high",
                            "l": "low", "c": "close", "v": "volume",
                            "n": "trades", "vw": "vwap"})
    df["datetime"] = (pd.to_datetime(df["datetime"], utc=True)
                        .dt.tz_convert("America/New_York")
                        .dt.tz_localize(None))
    cols = ["datetime", "open", "high", "low", "close", "volume"]
    df = df[[c for c in cols if c in df.columns]].sort_values("datetime")
    df = df.drop_duplicates(subset="datetime").reset_index(drop=True)

    # 정규장(09:30~15:59 ET)만 남긴다 — 전략이 정규장 기준
    t = df["datetime"].dt.time
    reg = (t >= pd.Timestamp("09:30").time()) & (t < pd.Timestamp("16:00").time())
    df_reg = df[reg].reset_index(drop=True)

    out = f"{SYMBOL}_{tf}.csv"
    df_reg.to_csv(out, index=False)

    days = df_reg["datetime"].dt.date.nunique()
    print(f"\n✅ 저장: {out}")
    print(f"   {len(df_reg):,}개 바 / {days:,}거래일")
    print(f"   {df_reg['datetime'].min()} ~ {df_reg['datetime'].max()}")
    print(f"   거래일당 평균 {len(df_reg)/days:.0f}개 "
          f"(정규장 완전하면 390개)")

    # 품질 점검 — 일봉과 대조하기 좋게 일별 OHLC 요약도 저장
    g = df_reg.set_index("datetime").groupby(pd.Grouper(freq="D"))
    daily = pd.DataFrame({
        "open": g["open"].first(), "high": g["high"].max(),
        "low": g["low"].min(), "close": g["close"].last(),
        "bars": g["close"].count()}).dropna()
    daily.to_csv(f"{SYMBOL}_daily_from_minute.csv")
    print(f"   일별 요약도 저장: {SYMBOL}_daily_from_minute.csv")
    print(f"\n   ⚠️ 이 일별 요약을 기존 일봉과 대조해 분할 조정이")
    print(f"      제대로 됐는지 먼저 확인하세요.")


if __name__ == "__main__":
    main()
