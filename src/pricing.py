import streamlit as st
import yfinance as yf

def price_refresh_controls(user, page_name: str, force_leap_mid: bool = False):
    uid = str(getattr(user, "id", user))
    prev = st.session_state.get("_current_page_name")
    if prev != page_name:
        try:
            st.cache_data.clear()
        except Exception:
            pass
        if force_leap_mid:
            st.session_state[f"leap_mid_autorefresh_{uid}"] = True
        st.session_state["_current_page_name"] = page_name

    if st.button(" Refresh Prices", key=f"refresh_prices_{page_name}_{uid}", type="primary"):
        try:
            st.cache_data.clear()
        except Exception:
            pass
        if force_leap_mid:
            st.session_state[f"leap_mid_autorefresh_{uid}"] = True
        st.rerun()

@st.cache_data(ttl=60)
def get_live_prices(symbols: list[str]) -> dict[str, float]:
    # batch fetch
    syms = sorted({s.strip().upper() for s in symbols if s and str(s).strip()})
    if not syms:
        return {}
    data = yf.download(syms, period="1d", interval="1m", progress=False, group_by="ticker", threads=True)
    out = {}
    # yfinance output varies for 1 vs many symbols; handle both
    if len(syms) == 1:
        s = syms[0]
        try:
            out[s] = float(data["Close"].dropna().iloc[-1])
        except Exception:
            pass
        return out

    for s in syms:
        try:
            out[s] = float(data[s]["Close"].dropna().iloc[-1])
        except Exception:
            pass
    return out
