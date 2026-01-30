import streamlit as st

def apply_global_ui_theme():
    """
    Minimal global UI tweaks that respect Streamlit's theme (config.toml).
    Colors should be controlled via .streamlit/config.toml for consistency.
    """
    st.markdown(
        """
        <style>
        /* Typography + spacing (no hard-coded colors) */
        .stApp {
            font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, "Apple Color Emoji", "Segoe UI Emoji";
        }
        [data-testid="stMainBlockContainer"] { padding-top: 1.25rem; padding-bottom: 2rem; }

        /* Consistent rounding */
        .stButton button, button[kind="primary"], button[kind="secondary"],
        .stTextInput input, .stNumberInput input, .stDateInput input,
        .stTextArea textarea, [data-baseweb="select"] > div,
        [data-testid="stDataFrame"], [data-testid="stMetric"], [data-testid="stExpander"] {
            border-radius: 12px !important;
        }

        /* Dataframe readability */
        [data-testid="stDataFrame"] thead tr th { font-weight: 700 !important; }
        [data-testid="stDataFrame"] tbody tr td { font-variant-numeric: tabular-nums; }
        </style>
        """,
        unsafe_allow_html=True,
    )

import pandas as pd
import altair as alt
import yfinance as yf
import re
from supabase import create_client, Client
from datetime import datetime, date, timedelta
import math
import os
import uuid

def _auto_refresh_prices_on_enter(user, page_name: str, also_force_leap_mid: bool = False):
    """
    Clears cache_data once per page entry so live share/option prices refresh.
    Optionally forces LEAP mid refresh (for Update LEAP Prices page).
    """
    nav_seq = int(st.session_state.get("_nav_seq", 0))
    key = f"_prices_refreshed_{page_name}_{user.id}"
    if st.session_state.get(key) != nav_seq:
        # Clear cached Yahoo calls so prices re-fetch
        try:
            st.cache_data.clear()
        except Exception:
            pass
        st.session_state[key] = nav_seq

        if also_force_leap_mid:
            # Reset the once/day guard so the page runs a refresh on entry
            today_key = f"leap_mid_autorefresh_{user.id}"
            st.session_state[today_key] = "__force__"

def force_light_mode():
    st.markdown("""
        <style>
        /* --- GLOBAL BACKGROUND (White) --- */
        .stApp {
            background-color: #FFFFFF;
            color: #000000;
        }
        
        /* --- SIDEBAR (Light Grey) --- */
        [data-testid="stSidebar"] {
            background-color: #F0F2F6;
            border-right: 1px solid #E6E6E6;
        }
        
        /* --- METRICS (Clean White Cards) --- */
        [data-testid="stMetric"] {
            background-color: #FFFFFF;
            border: 1px solid #E6E6E6;
            padding: 15px;
            border-radius: 8px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }
        [data-testid="stMetricLabel"] {
            color: #555555; /* Dark Grey for labels */
        }
        [data-testid="stMetricValue"] {
            color: #000000; /* Pitch Black for numbers */
        }

        /* --- INPUT FIELDS (Force White w/ Black Text) --- */
        /* Crucial for overriding system dark mode defaults */
        .stTextInput > div > div > input, 
        .stNumberInput > div > div > input,
        .stSelectbox > div > div > div {
            color: #000000 !important;
            background-color: #FFFFFF !important;
            border: 1px solid #D6D6D6;
        }
        
        /* --- DATAFRAMES --- */
        [data-testid="stDataFrame"] {
            border: 1px solid #E6E6E6;
        }
        
        /* --- HEADERS --- */
        h1, h2, h3, h4, h5, h6 {
            color: #000000 !important;
        }
        
        /* --- SIDEBAR TEXT (Readable) --- */
        [data-testid="stSidebar"] * { color: #111111 !important; }
        [data-testid="stSidebar"] a, [data-testid="stSidebar"] a * { color: #111111 !important; }
        [data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3 {
            color: #111111 !important; font-weight: 700 !important;
        }
        [data-testid="stSidebar"] [aria-selected="true"] {
            background: rgba(0,0,0,0.06) !important;
            border-radius: 8px;
        }
    </style>
    """, unsafe_allow_html=True)


# --------------------------------------------------------------------------------
# 0. CREDENTIALS
# --------------------------------------------------------------------------------
import os
import streamlit as st

def _get_secret(key: str, default: str = "") -> str:
    v = os.getenv(key)
    if v:
        return v
    try:
        if hasattr(st, "secrets") and st.secrets is not None and key in st.secrets:
            return st.secrets[key]
    except Exception:
        pass
    return default

# CHANGE IS HERE: Replaced the actual keys with empty strings ""
# If the keys aren't found in secrets, the app should probably fail or warn, 
# rather than fallback to a hardcoded string.
SUPABASE_URL = _get_secret("SUPABASE_URL", "")
SUPABASE_KEY = _get_secret("SUPABASE_KEY", "")

if not SUPABASE_URL or not SUPABASE_KEY:
    st.error("Missing Database Credentials! Please configure .streamlit/secrets.toml")
    st.stop()


# --------------------------------------------------------------------------------
# 1. APP CONFIGURATION
# --------------------------------------------------------------------------------
st.set_page_config(
    page_title="Pro Options Tracker",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
    <style>
    .stDataFrame { border: 1px solid #f0f2f6; }
    div[data-testid="stMetric"] { background-color: #f9f9f9; padding: 10px; border-radius: 5px; }
    
    /* Custom Table Styling */
    .finance-table {
        width: 100%;
        border-collapse: collapse;
        font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
        font-size: 0.95rem;
        margin-bottom: 20px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.1);
    }
    .finance-table th {
        background-color: #f0f2f6;
        text-align: right;
        padding: 10px 12px;
        font-weight: 600;
        border-bottom: 2px solid #d1d5db;
        color: #31333F;
    }
    .finance-table th:first-child, .finance-table td:first-child {
        text-align: left;
    }
    .finance-table td {
        padding: 10px 12px;
        text-align: right;
        border-bottom: 1px solid #f0f2f6;
        color: #31333F;
    }
    .finance-table tr:nth-child(even) { background-color: #f8f9fb; }
    .finance-table tr:hover { background-color: #eef2f6; }
    .finance-table .total-row {
        font-weight: bold;
        background-color: #e8f0fe !important;
        border-top: 2px solid #aecbfa;
    }
    .finance-table .total-row td { font-size: 1.05rem; color: #1a73e8; }
    .pos-val { color: #00703c; font-weight: 500; }
    .neg-val { color: #d93025; font-weight: 500; }
    .liability-alert { color: #d93025; font-weight: bold; }
    </style>
    """, unsafe_allow_html=True)

# --------------------------------------------------------------------------------
# 2. SUPABASE CONNECTION
# --------------------------------------------------------------------------------
@st.cache_resource
def init_connection():
    try:
        return create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        st.error(f"Failed to connect to Supabase: {e}")
        return None

supabase = init_connection()

def ensure_supabase_auth():
    """Attach the logged-in user's JWT to PostgREST so RLS-protected inserts/selects work."""
    if not supabase:
        return
    token = st.session_state.get("access_token")
    if token:
        try:
            supabase.postgrest.auth(token)
        except Exception:
            # Compatible with older supabase-py versions
            pass

# --------------------------------------------------------------------------------
# 3. AUTHENTICATION & SESSION
# --------------------------------------------------------------------------------
if 'user' not in st.session_state: st.session_state.user = None
if 'delete_confirm_id' not in st.session_state: st.session_state.delete_confirm_id = None

def handle_auth():
    st.sidebar.title("🔐 Access Portal")
    if not supabase: 
        st.warning("⚠️ Database not connected.")
        return False

    if st.session_state.user:
        st.sidebar.success(f"User: {st.session_state.user.email}")
        if st.sidebar.button("Logout"):
            supabase.auth.sign_out()
            st.session_state.user = None
            st.rerun()
        return True

    tab1, tab2 = st.sidebar.tabs(["Login", "Register"])
    with tab1:
        email = st.text_input("Email", key="login_email")
        password = st.text_input("Password", type="password", key="login_pass")
        if st.button("Sign In", type="primary"):
            try:
                res = supabase.auth.sign_in_with_password({"email": email, "password": password})
                st.session_state.user = res.user
                st.session_state.access_token = getattr(getattr(res, 'session', None), 'access_token', '') or ''
                ensure_supabase_auth()
                st.rerun()
            except Exception as e: st.error(f"Login failed: {e}")
    with tab2:
        new_email = st.text_input("Email", key="reg_email")
        new_pass = st.text_input("Password", type="password", key="reg_pass")
        if st.button("Create Account"):
            try:
                res = supabase.auth.sign_up({"email": new_email, "password": new_pass})
                st.success("Account created! Log in.")
            except Exception as e: st.error(f"Signup failed: {e}")
    return False

# --------------------------------------------------------------------------------
# 4. DATA HELPERS
# --------------------------------------------------------------------------------
def _iso_date(d_val):
    if d_val is None or (isinstance(d_val, float) and pd.isna(d_val)):
        return ""
    if isinstance(d_val, datetime):
        return d_val.date().isoformat()
    if isinstance(d_val, date):
        return d_val.isoformat()
    s = str(d_val).strip()
    if not s:
        return ""
    # Strip time if present
    s = s.split('T')[0].split(' ')[0]
    # Normalize common formats
    for fmt in ('%Y-%m-%d', '%m/%d/%Y', '%Y/%m/%d'):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except Exception:
            pass
    return s

def format_date_custom(d_val):
    if not d_val or pd.isna(d_val): return ""
    try:
        if isinstance(d_val, str):
            try: dt = datetime.fromisoformat(d_val)
            except: dt = datetime.strptime(d_val, '%Y-%m-%d')
            return dt.strftime('%Y-%b-%d')
        elif isinstance(d_val, (date, datetime)):
            return d_val.strftime('%Y-%b-%d')
        return str(d_val)
    except: return str(d_val)

def clean_number(val):
    if val is None or pd.isna(val) or val == "":
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip().replace('$', '').replace(',', '').replace(' ', '').replace('CAD', '').replace('USD', '')
    try: return float(s)
    except: return 0.0

def normalize_columns(df):
    if not df.empty:
        if 'ticker' in df.columns and 'symbol' not in df.columns: df['symbol'] = df['ticker']
        if 'strike_price' in df.columns and 'strike' not in df.columns: df['strike'] = df['strike_price']
        if 'expiration_date' in df.columns and 'expiration' not in df.columns: df['expiration'] = df['expiration_date']
        # If both exist, prefer expiration_date (some older rows may have wrong 'expiration')
        if 'expiration_date' in df.columns and 'expiration' in df.columns:
            df['expiration'] = df['expiration_date'].fillna(df['expiration'])
        if 'contracts' in df.columns:
            if 'quantity' not in df.columns: df['quantity'] = df['contracts']
            else: df['quantity'] = df['quantity'].fillna(df['contracts'])
        if 'quantity' in df.columns: df['quantity'] = df['quantity'].fillna(0)
    return df

def _fetch_all(query_builder, batch_size: int = 1000):
    """Fetch all rows from a Supabase query using range() pagination."""
    out = []
    start = 0
    while True:
        end = start + batch_size - 1
        res = query_builder.range(start, end).execute()
        data = getattr(res, "data", None) or []
        if not data:
            break
        out.extend(data)
        if len(data) < batch_size:
            break
        start += batch_size
    return out

def get_cash_balance(user_id):
    try:
        qb = supabase.table("transactions").select("amount")            .eq("user_id", user_id)            .eq("currency", "USD")
        rows = _fetch_all(qb)
        if not rows:
            return 0.0
        return float(pd.DataFrame(rows)["amount"].fillna(0).sum())
    except Exception as e:
        st.error(f"Cash balance query failed: {e}")
        return 0.0

def get_net_invested_cad(user_id):
    try:
        response = supabase.table("transactions").select("amount").eq("user_id", user_id).eq("currency", "CAD").in_("type", ["DEPOSIT", "WITHDRAWAL"]).execute()
        df = pd.DataFrame(response.data)
        return df['amount'].sum() if not df.empty else 0.0
    except: return 0.0

@st.cache_data(ttl=60)
def get_live_stock_price(symbol):
    """
    Fetches the latest live price for a given symbol.
    Handles weekends (looking back 5 days) and cleans messy symbols.
    """
    if not symbol: return 0.0

    # --- 1. CLEANING LOGIC (Fixes the "Delisted" error) ---
    # Convert to string just in case
    s = str(symbol)
    
    # If the symbol looks like "Company Name (TICKER)", grab the part inside ()
    # Example: "SOFI TECHNOLOGIES (SOFI)" -> "SOFI"
    match = re.search(r'\((.*?)\)', s)
    if match:
        s = match.group(1)  # Take only what is inside the parens

    # If the symbol looks like "XNAS:SOFI", split by ":" and take the last part
    if ":" in s:
        s = s.split(":")[-1]

    # Final cleanup: Remove spaces and make uppercase
    clean_sym = s.strip().upper()
    # -------------------------------------------------------

    # Handle Cash/Currency manually
    if clean_sym in ["USD", "CAD", "USD/CAD", "CAD/USD", "CASH"]:
        return 1.0

    try:
        ticker = yf.Ticker(clean_sym)
        
        # STRATEGY 1: Check fast_info (Real-time)
        try:
            price = ticker.fast_info.last_price
            if price and not pd.isna(price) and price > 0: 
                return float(price)
        except: pass

        # STRATEGY 2: Check History (Back 5 days for weekends)
        # We look back 5 days to ensure we hit a weekday if it's currently Sat/Sun
        hist = ticker.history(period="5d")
        if not hist.empty:
            return float(hist['Close'].iloc[-1])
        
        # STRATEGY 3: Last Resort (Previous Close)
        try:
            return float(ticker.info.get('previousClose', 0.0))
        except: pass

        return 0.0
    except: 
        # If it fails, return 0 so the dashboard falls back to your manual price
        return 0.0


@st.cache_data(ttl=300)
def _yahoo_option_chain(symbol: str, expiry: str):
    """Return (calls_df, puts_df) for a given symbol/expiry from Yahoo Finance via yfinance."""
    t = yf.Ticker(symbol)
    chain = t.option_chain(expiry)
    return chain.calls, chain.puts

def _clean_symbol_for_yahoo(symbol: str) -> str:
    """Best-effort symbol cleaning to avoid yfinance 'delisted' issues."""
    if not symbol:
        return ""
    s = str(symbol)
    m = re.search(r'\((.*?)\)', s)
    if m:
        s = m.group(1)
    if ":" in s:
        s = s.split(":")[-1]
    return s.strip().upper()

def get_yahoo_option_mid_price(symbol: str, expiry, strike, right: str):
    """Get Yahoo mid price ( (bid+ask)/2 ) for an option contract, with sensible fallbacks.

    Returns float or None if not found.
    """
    sym = _clean_symbol_for_yahoo(symbol)
    exp = _iso_date(expiry)
    try:
        k = float(strike)
    except Exception:
        return None
    if not sym or not exp:
        return None

    try:
        calls, puts = _yahoo_option_chain(sym, exp)
        df = calls if str(right).upper().startswith("C") else puts
        if df is None or df.empty or "strike" not in df.columns:
            return None

        diffs = (df["strike"].astype(float) - k).abs()
        idx = diffs.idxmin()
        if float(diffs.loc[idx]) > 0.001:  # require an exact-ish match
            return None

        row = df.loc[idx]
        bid = float(row.get("bid") or 0.0)
        ask = float(row.get("ask") or 0.0)
        last = float(row.get("lastPrice") or 0.0)

        if bid > 0 and ask > 0:
            return round((bid + ask) / 2.0, 4)
        if last > 0:
            return round(last, 4)
        if bid > 0:
            return round(bid, 4)
        if ask > 0:
            return round(ask, 4)
        return None
    except Exception:
        return None


@st.cache_data(ttl=3600)
def get_usd_to_cad_rate():
    try:
        ticker = yf.Ticker("CAD=X")
        hist = ticker.history(period="1d")
        if not hist.empty: return hist['Close'].iloc[-1]
    except: pass
    return 1.40 

def get_portfolio_data(user_id):
    assets_res = supabase.table("assets").select("*").eq("user_id", user_id).neq("quantity", 0).execute()
    assets_df = pd.DataFrame(assets_res.data)
    assets_df = normalize_columns(assets_df)
    
    options_res = supabase.table("options").select("*").eq("user_id", user_id).eq("status", "open").execute()
    options_df = pd.DataFrame(options_res.data)
    options_df = normalize_columns(options_df)
    return assets_df, options_df

def get_portfolio_history(user_id):
    try:
        res = supabase.table("portfolio_history").select("*").eq("user_id", user_id).order("snapshot_date", desc=False).execute()
        return pd.DataFrame(res.data)
    except: return pd.DataFrame()

def get_baseline_snapshot(user_id):
    try:
        current_year = date.today().year
        prev_year_end = f"{current_year - 1}-12-31"
        res = supabase.table("portfolio_history").select("*").eq("user_id", user_id).eq("snapshot_date", prev_year_end).execute()
        if res.data: return res.data[0] 
        res = supabase.table("portfolio_history").select("*").eq("user_id", user_id).gte("snapshot_date", f"{current_year}-01-01").order("snapshot_date", desc=False).limit(1).execute()
        if res.data: return res.data[0]
        return None
    except: return None

def log_transaction(user_id, description, amount, trade_type, symbol, date_obj, currency="USD", txg: str | None = None):
    # 1. Force Amount to Float (prevents Numpy errors)
    try: safe_amount = float(amount)
    except: safe_amount = 0.0

    # Optional transaction group tag (used for grouped Ledger transactions)
    if txg:
        if f"TXG:{txg}" not in str(description):
            description = f"{description} | TXG:{txg}"
    
    # 2. Force Date to ISO String (YYYY-MM-DD) - Prevents timestamp mismatch
    if isinstance(date_obj, datetime):
        date_str = date_obj.date().isoformat()
    elif isinstance(date_obj, date):
        date_str = date_obj.isoformat()
    else:
        # Fallback for strings, strip time if present
        date_str = str(date_obj).split('T')[0]

    data = {
        "user_id": user_id, 
        "description": description, 
        "amount": safe_amount,
        "type": trade_type, 
        "related_symbol": str(symbol).upper(), 
        "transaction_date": date_str, 
        "currency": currency 
    }
    
    # 3. Execute with Error Logging
    try:
        supabase.table("transactions").insert(data).execute()
    except Exception as e:
        st.error(f"Failed to record transaction (DB insert): {e}")
        raise

# --------------------------------------------------------------------------------
# 5. CORE LOGIC
# --------------------------------------------------------------------------------
def update_asset_position(user_id, symbol, quantity, price, action, date_obj, asset_type="STOCK", expiration=None, strike=None, fees=0.0, txg: str | None = None):
    cost = quantity * price
    multiplier = 100 if "LEAP" in asset_type or "OPTION" in asset_type else 1
    txn_gross = cost * multiplier
    
    # Fee Logic:
    # Buy: You pay (Price * Qty) + Fees -> Cash goes down by total
    # Sell: You receive (Price * Qty) - Fees -> Cash goes up by net
    if action == "Buy":
        cash_impact = -(txn_gross + fees)
    else:
        cash_impact = txn_gross - fees
    
    desc_label = f"{action} {quantity} {symbol}"
    if expiration: desc_label += f" {expiration} ${strike}"
    desc_label += f" @ ${price:,.2f}"
    if fees > 0: desc_label += f" (Fees: ${fees:.2f})"
    
    log_transaction(user_id, desc_label, cash_impact, "TRADE_" + asset_type, symbol, date_obj, currency="USD", txg=txg)
    
    query = supabase.table("assets").select("*").eq("user_id", user_id).eq("ticker", symbol)
    if "LEAP" in asset_type: query = query.like("type", "LEAP%").eq("strike_price", strike).eq("expiration", str(expiration))
    else: query = query.eq("type", "STOCK")
    existing = query.execute()
    
    if existing.data:
        row = existing.data[0]
        old_qty = row['quantity']; old_cost = row.get('cost_basis', 0)
        if action == "Buy":
            new_qty = old_qty + quantity
            current_val = old_qty * old_cost
            # Capitalize fees into the cost basis on BUY
            add_val = (quantity * price * multiplier) + fees
            # Divide by multiplier to get per-share/per-contract basis
            new_cost = (current_val + (add_val / multiplier)) / new_qty if new_qty != 0 else 0
        else: 
            new_qty = old_qty - quantity; new_cost = old_cost
        supabase.table("assets").update({"quantity": new_qty, "cost_basis": new_cost}).eq("id", row['id']).execute()
    else:
        qty_to_insert = quantity if action == "Buy" else -quantity
        # Initial cost basis includes fees
        initial_cost = (price * multiplier + fees) / multiplier if action == "Buy" else price
        data = { "user_id": user_id, "ticker": symbol, "symbol": symbol, "quantity": qty_to_insert, "type": asset_type, "cost_basis": initial_cost, "date_acquired": date_obj.isoformat(), "last_price": price }
        if strike: data["strike_price"] = strike
        if expiration: data["expiration"] = str(expiration)
        supabase.table("assets").insert(data).execute()

def update_short_option_position(user_id, symbol, quantity, price, action, date_obj, opt_type, expiration, strike, fees=0.0, linked_asset_id_override=None, txg: str | None = None):
    premium = quantity * price * 100
    exp_iso = _iso_date(expiration)
    
    # Fee Logic:
    # Sell (Open): Receive Premium - Fees
    # Buy (Close): Pay Premium + Fees
    if action == "Sell":
        cash_impact = premium - fees
    else:
        cash_impact = -(premium + fees)
        
    formatted_exp = format_date_custom(exp_iso)
    desc = f"{action} {quantity} {symbol} {formatted_exp} ${strike} {opt_type}"
    if fees > 0: desc += f" (Fees: ${fees:.2f})"
    
    log_transaction(user_id, desc, cash_impact, "OPTION_PREMIUM", symbol, date_obj, currency="USD", txg=txg)
    
    if action == "Sell":
        linked_asset_id = None
        if opt_type == "CALL":
            stocks = supabase.table("assets").select("*").eq("user_id", user_id).eq("ticker", symbol).eq("type", "STOCK").neq("quantity", 0).execute()
            if stocks.data: linked_asset_id = stocks.data[0]['id']
            else:
                leaps = supabase.table("assets").select("*").eq("user_id", user_id).eq("ticker", symbol).neq("type", "STOCK").neq("quantity", 0).execute()
                if leaps.data: linked_asset_id = leaps.data[0]['id']
        if linked_asset_id_override is not None:
            linked_asset_id = linked_asset_id_override

        payload = { 
            "user_id": user_id, "ticker": symbol, "symbol": symbol, "strike_price": strike, "expiration_date": exp_iso, "expiration": exp_iso, "open_date": date_obj.isoformat(), "type": opt_type, 
            "contracts": int(quantity), "premium_received": price, "status": "open", "linked_asset_id": linked_asset_id
        }
        supabase.table("options").insert(payload).execute()
    else:
        res = supabase.table("options").select("*").eq("user_id", user_id).eq("symbol", symbol).eq("strike_price", strike).eq("expiration_date", exp_iso).eq("type", opt_type).eq("status", "open").execute()
        remaining_to_close = int(quantity)
        if res.data:
            for row in res.data:
                if remaining_to_close <= 0: break
                avail = row['contracts']
                if avail <= remaining_to_close: supabase.table("options").update({"status": "closed"}).eq("id", row['id']).execute(); remaining_to_close -= avail
                else: left = avail - remaining_to_close; supabase.table("options").update({"contracts": left}).eq("id", row['id']).execute(); remaining_to_close = 0

def handle_assignment(user_id, option_id, symbol, strike, type_, quantity):
    supabase.table("options").update({"status": "assigned"}).eq("id", option_id).execute()
    trade_date = datetime.now().date()
    if type_ == "PUT": update_asset_position(user_id, symbol, quantity * 100, strike, "Buy", trade_date, "STOCK"); st.success(f"Assigned on PUT. Bought {quantity*100} shares.")
    elif type_ == "CALL": update_asset_position(user_id, symbol, quantity * 100, strike, "Sell", trade_date, "STOCK"); st.success(f"Assigned on CALL. Sold {quantity*100} shares.")

def capture_snapshot(user_id, total_eq_usd, ex_rate, snap_date):
    existing = supabase.table("portfolio_history").select("id").eq("user_id", user_id).eq("snapshot_date", snap_date.isoformat()).execute()
    if existing.data: supabase.table("portfolio_history").update({ "total_equity": total_eq_usd, "exchange_rate": ex_rate, "currency": "USD" }).eq("id", existing.data[0]['id']).execute()
    else: supabase.table("portfolio_history").insert({ "user_id": user_id, "snapshot_date": snap_date.strftime("%Y-%m-%d"), "total_equity": total_eq_usd, "exchange_rate": ex_rate, "cash_balance": 0, "stock_value": 0, "long_option_value": 0, "short_liability_estimate": 0, "currency": "USD" }).execute()

def get_net_liquidation_usd(user_id):
    # NET LIQUIDATION VALUE (Ignoring ITM Puts)
    cash_usd = get_cash_balance(user_id)
    assets, options = get_portfolio_data(user_id)
    
    asset_val = 0.0
    if not assets.empty:
        for _, row in assets.iterrows():
            qty = clean_number(row['quantity'])
            if row['type'] == 'STOCK': 
                price = get_live_stock_price(row['symbol']); 
                if price == 0: price = clean_number(row.get('last_price', 0))
                asset_val += (qty * price)
            elif 'LEAP' in row['type'] or 'LONG' in row['type']: 
                price = clean_number(row.get('last_price', 0))
                asset_val += (qty * 100 * price)
    
    liability_val = 0.0
    if not options.empty:
        for _, row in options.iterrows():
            qty = abs(clean_number(row.get('quantity') or row.get('contracts') or 0))
            strike = clean_number(row.get('strike_price') or row.get('strike') or 0)
            price = get_live_stock_price(row['symbol'])
            typ = str(row.get('type', '')).upper()
            
            # ONLY SUBTRACT LIABILITY IF IT IS AN ITM CALL
            if price > 0 and "CALL" in typ and price > strike:
                intrinsic = (price - strike)
                liability_val += (intrinsic * qty * 100)
                
    return cash_usd + asset_val - liability_val

def get_distinct_holdings(user_id):
    try:
        res = supabase.table("assets").select("ticker").eq("user_id", user_id).neq("quantity", 0).execute()
        if res.data: return sorted(list({row['ticker'] for row in res.data}))
        return []
    except: return []

def get_holdings_for_symbol(user_id, symbol):
    try:
        res = supabase.table("assets").select("*").eq("user_id", user_id).eq("ticker", symbol).neq("quantity", 0).execute()
        return res.data
    except: return []

def get_locked_collateral(user_id):
    """Returns {asset_id: contracts_used} for open options with linked collateral.

    NOTE: Supabase may return ids as int or str depending on schema; we normalize keys to str.
    """
    try:
        res = (
            supabase.table("options")
            .select("linked_asset_id, contracts")
            .eq("user_id", user_id)
            .eq("status", "open")
            .not_.is_("linked_asset_id", "null")
            .execute()
        )
        locked = {}
        for r in (res.data or []):
            aid = r.get('linked_asset_id')
            if aid is None:
                continue
            key = str(aid)
            locked[key] = locked.get(key, 0) + int(r.get('contracts', 0) or 0)
        return locked
    except:
        return {}


def get_open_short_call_contracts(user_id, symbol):
    """Total open short CALL contracts for a ticker (used to infer collateral usage when linked_asset_id is missing)."""
    try:
        res = (
            supabase.table("options")
            .select("contracts")
            .eq("user_id", user_id)
            .eq("symbol", symbol)
            .eq("status", "open")
            .eq("type", "CALL")
            .execute()
        )
        return int(sum(int(r.get("contracts", 0) or 0) for r in (res.data or [])))
    except:
        return 0

# --------------------------------------------------------------------------------
# 6. DASHBOARD & PAGES
# --------------------------------------------------------------------------------

def dashboard_page(user):
    st.header("📊 Executive Dashboard")


    # Auto-refresh share/LEAP prices on page entry
    _auto_refresh_prices_on_enter(user, 'Dashboard', also_force_leap_mid=False)
    # Manual refresh button
    if st.button("🔄 Refresh Prices", key=f"refresh_prices_{page_name}_{user.id}", type="primary"):
        st.cache_data.clear()
        st.rerun()

    # No currency selector; we show both USD and CAD in the summary + portfolio value table
    fx = float(get_usd_to_cad_rate() or 1.0)
    st.caption(f"Exchange Rate (live): 1 USD = {fx:.4f} CAD")

    # --- Data Loading ---
    cash_usd = float(get_cash_balance(user.id) or 0.0)
    assets, options = get_portfolio_data(user.id)

    # Normalize asset types
    try:
        if not assets.empty and 'type' in assets.columns:
            assets['type_norm'] = assets['type'].astype(str).str.upper().str.strip()
        else:
            assets['type_norm'] = 'STOCK'
    except Exception:
        assets['type_norm'] = 'STOCK'

    # --- Calculations (USD) ---
    stock_value_usd = 0.0
    leap_value_usd = 0.0
    itm_liability_usd = 0.0

    # 1. Assets Calculation (same logic as option details)
    if not assets.empty:
        for idx_row, row in assets.iterrows():
            qty = clean_number(row.get('quantity', 0))
            r_type_raw = str(row.get('type', '')).upper().strip()
            assets.at[idx_row, 'type_norm'] = r_type_raw
            r_type_disp = r_type_raw.replace('LONG_', 'LEAP ').replace('LEAP_', 'LEAP ')
            assets.at[idx_row, 'type_disp'] = r_type_disp

            if r_type_raw == 'STOCK':
                sym = str(row.get('symbol', row.get('ticker', ''))).strip().upper()
                live_price = get_live_stock_price(sym)
                if live_price == 0:
                    live_price = clean_number(row.get('last_price', 0))
                assets.at[idx_row, 'current_price'] = live_price
                assets.at[idx_row, 'market_value'] = qty * live_price
                stock_value_usd += (qty * live_price)
            else:
                # LEAP/LONG options: use manual last_price as current_price
                manual_price = clean_number(row.get('last_price', 0))
                assets.at[idx_row, 'current_price'] = manual_price
                assets.at[idx_row, 'market_value'] = qty * 100 * manual_price
                # We'll recompute leap_value_usd after loop to guarantee consistency

    # Ensure LEAP Equity matches table formula exactly: qty * 100 * current_price
    try:
        leap_value_usd = 0.0
        if not assets.empty and 'type_norm' in assets.columns:
            non_stock = assets[assets['type_norm'] != 'STOCK'].copy()
            if not non_stock.empty:
                non_stock['qty_num'] = pd.to_numeric(non_stock.get('quantity', 0), errors='coerce').fillna(0)
                non_stock['px_num'] = pd.to_numeric(non_stock.get('current_price', non_stock.get('last_price', 0)), errors='coerce').fillna(0)
                leap_value_usd = float((non_stock['qty_num'] * 100.0 * non_stock['px_num']).sum())
    except Exception:
        leap_value_usd = 0.0

    # 2. Options Liability (ITM CALL intrinsic only)
    grouped_options = {}
    if not options.empty:
        for _, row in options.iterrows():
            qty = abs(clean_number(row.get('quantity') or row.get('contracts') or 0))
            strike = float(clean_number(row.get('strike_price') or row.get('strike') or 0))
            sym = str(row.get('symbol', row.get('ticker', ''))).strip().upper()
            opt_type = str(row.get('type', '')).strip().upper()

            raw_exp = row.get('expiration')
            if raw_exp is None or pd.isna(raw_exp):
                raw_exp = row.get('expiration_date')
            exp_str = str(raw_exp) if raw_exp else ""

            underlying_price = get_live_stock_price(sym)

            intrinsic_val = 0.0
            if underlying_price > 0 and "CALL" in opt_type and underlying_price > strike:
                intrinsic_val = (underlying_price - strike) * qty * 100

            itm_liability_usd += intrinsic_val

            key = (sym, opt_type, exp_str, strike)
            if key not in grouped_options:
                grouped_options[key] = {
                    'symbol': sym,
                    'type': opt_type,
                    'expiration': exp_str,
                    'strike': strike,
                    'qty': 0.0,
                    'price': underlying_price,
                    'liability': 0.0,
                    'constituents': [],
                    'linked_assets': []
                }

            grouped_options[key]['qty'] += qty
            grouped_options[key]['liability'] += intrinsic_val

            old_premium = row.get('premium_received')
            if old_premium is None:
                old_premium = row.get('cost_basis', 0)

            lid = row.get('linked_asset_id')
            if lid and not pd.isna(lid):
                grouped_options[key]['linked_assets'].append(str(lid))

            grouped_options[key]['constituents'].append({
                'id': row['id'],
                'qty': qty,
                'cost_basis': row.get('cost_basis', 0),
                'premium_received': old_premium,
                'open_date': row.get('open_date'),
                'linked_asset_id': lid
            })

    net_liq_usd = cash_usd + stock_value_usd + leap_value_usd - itm_liability_usd
    net_liq_cad = net_liq_usd * fx

    # --------------------------------------------------------------------------------
    # TOP SUMMARY (flow-adjusted returns, exclude deposits/withdrawals)
    # --------------------------------------------------------------------------------
    # --------------------------------------------------------------------------------
    # Performance periods (exclude deposits/withdrawals from P/L)
    # NOTE: We anchor MTD/YTD off your weekly snapshots in portfolio_history.
    # --------------------------------------------------------------------------------
    today = date.today()
    fx = float(get_usd_to_cad_rate())

    def _net_flows_usd(d0, d1):
        """Net DEPOSIT/WITHDRAWAL flows in USD between (d0, d1], using transaction_date."""
        try:
            tx_res = supabase.table("transactions").select("transaction_date, amount, type, currency")\
                .eq("user_id", user.id).in_("type", ["DEPOSIT", "WITHDRAWAL"]).execute()
            tx = pd.DataFrame(tx_res.data)
            if tx.empty:
                return 0.0
            tx = tx[tx["currency"] == "USD"].copy()
            tx["transaction_date"] = pd.to_datetime(tx["transaction_date"], errors="coerce")
            tx = tx[tx["transaction_date"].notna()]
            mask = (tx["transaction_date"] > pd.to_datetime(d0)) & (tx["transaction_date"] <= pd.to_datetime(d1))
            return float(tx.loc[mask, "amount"].sum())
        except Exception:
            return 0.0

    # Pull snapshots once
    hist = get_portfolio_history(user.id)
    if not hist.empty:
        hist = hist.copy()
        hist["snapshot_date"] = pd.to_datetime(hist["snapshot_date"], errors="coerce")
        hist = hist[hist["snapshot_date"].notna()].sort_values("snapshot_date")
        hist["snap_d"] = hist["snapshot_date"].dt.date
    else:
        hist = pd.DataFrame(columns=["snapshot_date", "total_equity", "snap_d"])

    def _last_snapshot_on_or_before(d):
        if hist.empty:
            return None, None
        sub = hist[hist["snap_d"] <= d]
        if sub.empty:
            return None, None
        r = sub.iloc[-1]
        return float(r["total_equity"]), r["snap_d"]

    # --- WTD base: last snapshot (typically last Friday) ---
    w_base_eq, w_base_d = _last_snapshot_on_or_before(today)
    if w_base_eq is None:
        # If no snapshots, treat base as current minus deposits since inception (best-effort)
        w_base_eq, w_base_d = 0.0, today
    w_flows = _net_flows_usd(w_base_d, today)
    w_base_cap = w_base_eq + w_flows
    wtd_profit = net_liq_usd - w_base_cap
    wtd_pct = (wtd_profit / w_base_cap) if w_base_cap != 0 else 0.0

    # --- MTD base: last snapshot strictly before the first of this month (so in January, MTD==YTD) ---
    month_start = date(today.year, today.month, 1)
    m_base_eq, m_base_d = _last_snapshot_on_or_before(month_start - timedelta(days=1))
    if m_base_eq is None:
        # Fallback: first snapshot in month (or 0)
        if not hist.empty:
            sub = hist[hist["snap_d"] >= month_start]
            if not sub.empty:
                r = sub.iloc[0]
                m_base_eq, m_base_d = float(r["total_equity"]), r["snap_d"]
            else:
                m_base_eq, m_base_d = 0.0, month_start
        else:
            m_base_eq, m_base_d = 0.0, month_start
    m_flows = _net_flows_usd(m_base_d, today)
    m_base_cap = m_base_eq + m_flows
    mtd_profit = net_liq_usd - m_base_cap
    mtd_pct = (mtd_profit / m_base_cap) if m_base_cap != 0 else 0.0

    # --- YTD base: snapshot on Dec 31 of prior year if present, else last snapshot before Jan 1 ---
    year_start = date(today.year, 1, 1)
    dec31 = date(today.year - 1, 12, 31)
    y_base_eq, y_base_d = _last_snapshot_on_or_before(dec31)
    if y_base_eq is None:
        # If nothing before year start, use first snapshot in year
        if not hist.empty:
            sub = hist[hist["snap_d"] >= year_start]
            if not sub.empty:
                r = sub.iloc[0]
                y_base_eq, y_base_d = float(r["total_equity"]), r["snap_d"]
            else:
                y_base_eq, y_base_d = 0.0, year_start
        else:
            y_base_eq, y_base_d = 0.0, year_start

    # --- YTD compound: product of weekly (flow-adjusted) returns since Jan 1 ---
    def _ytd_compound_from_snapshots():
        if hist.empty:
            return 0.0, 0.0, 0
        snaps = hist[hist["snap_d"] >= year_start].copy()
        if snaps.empty:
            return 0.0, 0.0, 0
        # Ensure we include the base snapshot if it's before Jan 1 (e.g., Dec 31)
        base_eq, base_d = y_base_eq, y_base_d
        prod = 1.0
        prev_d = base_d
        prev_eq = base_eq

        for _, r in snaps.iterrows():
            d = r["snap_d"]
            eq = float(r["total_equity"])
            if d <= prev_d:
                continue
            net_flow = _net_flows_usd(prev_d, d)
            base_cap = prev_eq + net_flow
            profit = eq - base_cap
            ret = (profit / base_cap) if base_cap != 0 else 0.0
            prod *= (1.0 + ret)
            prev_d, prev_eq = d, eq

        # Include partial period from last snapshot to today
        net_flow = _net_flows_usd(prev_d, today)
        base_cap = prev_eq + net_flow
        profit = net_liq_usd - base_cap
        ret = (profit / base_cap) if base_cap != 0 else 0.0
        prod *= (1.0 + ret)

        ytd_pct_local = prod - 1.0

        # YTD profit dollars relative to base (also flow-adjusted)
        total_flows = _net_flows_usd(y_base_d, today)
        ytd_profit_local = net_liq_usd - (y_base_eq + total_flows)
        weeks_elapsed = max(1, int((today - year_start).days // 7) + 1)
        return ytd_profit_local, ytd_pct_local, weeks_elapsed

    ytd_profit, ytd_pct, ytd_weeks = _ytd_compound_from_snapshots()

    # FY Run Rate: annualize YTD return (based on elapsed days)
    days_elapsed = max(1, (today - year_start).days)
    fy_profit = ytd_profit * (365.0 / days_elapsed)
    fy_pct = ((1.0 + ytd_pct) ** (365.0 / days_elapsed) - 1.0) if ytd_pct > -1 else 0.0


    # Lifetime: compound the *Weekly %* from the Weekly Snapshot calculation (flow-normalized)
    # This compounds week-over-week and therefore ignores deposits/withdrawals (they are normalized out in Weekly %).
    def _lifetime_compound_from_weekly_snapshot_pct():
        try:
            hist_df = get_portfolio_history(user.id)
            if hist_df is None or hist_df.empty:
                return None

            hist_df = normalize_columns(hist_df)
            if "snapshot_date" not in hist_df.columns or "total_equity" not in hist_df.columns:
                return None

            hist_df = hist_df[["snapshot_date", "total_equity"]].copy()
            hist_df["snapshot_date"] = pd.to_datetime(hist_df["snapshot_date"], errors="coerce")
            hist_df["total_equity"] = pd.to_numeric(hist_df["total_equity"], errors="coerce")
            hist_df = hist_df.dropna(subset=["snapshot_date", "total_equity"]).sort_values("snapshot_date", ascending=True)
            if hist_df.empty:
                return None

            # Transactions needed to compute Weekly % (flow-normalized)
            tx_res = supabase.table("transactions").select("transaction_date, amount, type, currency")                .eq("user_id", user.id).in_("type", ["DEPOSIT", "WITHDRAWAL"]).execute()
            tx_df = pd.DataFrame(tx_res.data)
            if not tx_df.empty:
                tx_df = normalize_columns(tx_df)
                tx_df["transaction_date"] = pd.to_datetime(tx_df["transaction_date"], errors="coerce")
                tx_df["amount"] = pd.to_numeric(tx_df["amount"], errors="coerce")
                tx_df = tx_df.dropna(subset=["transaction_date", "amount"])
                # Keep USD flows only for USD equity snapshots
                if "currency" in tx_df.columns:
                    tx_df = tx_df[tx_df["currency"].astype(str).str.upper() == "USD"]
            else:
                tx_df = pd.DataFrame(columns=["transaction_date", "amount", "type", "currency"])

            weekly_rets = []
            weekly_profits = []
            for i in range(len(hist_df)):
                curr_date = hist_df.iloc[i]["snapshot_date"]
                curr_eq = float(hist_df.iloc[i]["total_equity"])

                if i == 0:
                    prev_date = pd.Timestamp.min
                    prev_eq = 0.0
                else:
                    prev_date = hist_df.iloc[i-1]["snapshot_date"]
                    prev_eq = float(hist_df.iloc[i-1]["total_equity"])

                net_flow = 0.0
                if not tx_df.empty:
                    mask = (tx_df["transaction_date"] > prev_date) & (tx_df["transaction_date"] <= curr_date)
                    net_flow = float(tx_df.loc[mask, "amount"].sum())

                base_capital = prev_eq + net_flow
                weekly_profit = curr_eq - base_capital

                if i == 0 or base_capital == 0:
                    weekly_ret = 0.0
                else:
                    weekly_ret = weekly_profit / base_capital

                weekly_rets.append(float(weekly_ret))
                weekly_profits.append(float(weekly_profit))

            # Compound Weekly % week-over-week (skip first row which is always 0)
            prod = 1.0
            for r in weekly_rets[1:]:
                # guard against NaN/inf
                if r is None or (isinstance(r, float) and (math.isinf(r) or math.isnan(r))):
                    r = 0.0
                prod *= (1.0 + float(r))
            life_pct_local = float(prod - 1.0)

            # Lifetime profit dollars: sum of flow-normalized weekly P/L values (ignores deposits/withdrawals).
            # This matches your request to "just add the weekly P/L" week-over-week.
            life_profit_local = float(sum(weekly_profits[1:])) if len(weekly_profits) > 1 else 0.0

            return life_profit_local, life_pct_local

        except Exception:
            return None

    def _rolling_52w_from_weekly_snapshot_pct():
        """Return (profit_usd, pct) for trailing 52 weeks based on the same Weekly % logic used in the History tab.
        Uses portfolio_history weekly snapshots and flow-normalizes weekly returns using DEPOSIT/WITHDRAWAL transactions.
        """
        try:
            hist_df = get_portfolio_history(user.id)
            if hist_df is None or hist_df.empty:
                return None

            hist_df = normalize_columns(hist_df)
            if "snapshot_date" not in hist_df.columns or "total_equity" not in hist_df.columns:
                return None

            hist_df = hist_df[["snapshot_date", "total_equity"]].copy()
            hist_df["snapshot_date"] = pd.to_datetime(hist_df["snapshot_date"], errors="coerce")
            hist_df["total_equity"] = pd.to_numeric(hist_df["total_equity"], errors="coerce")
            hist_df = hist_df.dropna(subset=["snapshot_date", "total_equity"]).sort_values("snapshot_date", ascending=True)
            if len(hist_df) < 2:
                return 0.0, 0.0

            # Transactions needed to compute Weekly % (flow-normalized)
            tx_res = supabase.table("transactions").select("transaction_date, amount, type, currency")                .eq("user_id", user.id).in_("type", ["DEPOSIT", "WITHDRAWAL"]).execute()
            tx_df = pd.DataFrame(tx_res.data)
            if not tx_df.empty:
                tx_df = normalize_columns(tx_df)
                tx_df["transaction_date"] = pd.to_datetime(tx_df["transaction_date"], errors="coerce")
                tx_df["amount"] = pd.to_numeric(tx_df["amount"], errors="coerce")
                tx_df = tx_df.dropna(subset=["transaction_date", "amount"])
                if "currency" in tx_df.columns:
                    tx_df = tx_df[tx_df["currency"].astype(str).str.upper() == "USD"]
            else:
                tx_df = pd.DataFrame(columns=["transaction_date", "amount", "type", "currency"])

            weekly_rets = []
            weekly_profits = []
            weekly_flows = []
            for i in range(len(hist_df)):
                curr_date = hist_df.iloc[i]["snapshot_date"]
                curr_eq = float(hist_df.iloc[i]["total_equity"])

                if i == 0:
                    prev_date = pd.Timestamp.min
                    prev_eq = 0.0
                else:
                    prev_date = hist_df.iloc[i-1]["snapshot_date"]
                    prev_eq = float(hist_df.iloc[i-1]["total_equity"])

                net_flow = 0.0
                if not tx_df.empty:
                    mask = (tx_df["transaction_date"] > prev_date) & (tx_df["transaction_date"] <= curr_date)
                    net_flow = float(tx_df.loc[mask, "amount"].sum())

                base_capital = prev_eq + net_flow
                weekly_profit = curr_eq - base_capital

                if i == 0 or base_capital == 0:
                    weekly_ret = 0.0
                else:
                    weekly_ret = weekly_profit / base_capital

                weekly_rets.append(float(weekly_ret))
                weekly_profits.append(float(weekly_profit))
                weekly_flows.append(float(net_flow))

            # Trailing 52 weeks: compound last 52 weekly returns ending at last snapshot
            end_i = len(hist_df) - 1
            start_k = max(1, end_i - 51)  # matches History tab logic
            window_rets = [float(weekly_rets[k]) for k in range(start_k, end_i + 1)]
            prod = 1.0
            for r in window_rets:
                if r is None or (isinstance(r, float) and (math.isinf(r) or math.isnan(r))):
                    r = 0.0
                prod *= (1.0 + float(r))
            pct_52w = float(prod - 1.0) if window_rets else 0.0

            # Dollar profit over same window: sum of flow-normalized weekly P/L values in the window.
            # This ignores deposits/withdrawals by construction (weekly_profit = curr_eq - (prev_eq + net_flow)).
            profit_52w = float(sum(weekly_profits[start_k:end_i + 1])) if (end_i >= start_k) else 0.0
            return profit_52w, pct_52w

        except Exception:
            return None

    _life = _lifetime_compound_from_weekly_snapshot_pct()

    if _life is not None:
        life_profit, life_pct = _life
    else:
        # Fallback: previous behavior (vs total net deposits)
        try:
            tx_res = supabase.table("transactions").select("amount,type,currency")\
                .eq("user_id", user.id).in_("type", ["DEPOSIT", "WITHDRAWAL"]).execute()
            tx = pd.DataFrame(tx_res.data)
            life_flow = float(tx[tx["currency"] == "USD"]["amount"].sum()) if not tx.empty else 0.0
        except Exception:
            life_flow = 0.0
        life_base = life_flow
        life_profit = net_liq_usd - life_base
        life_pct = (life_profit / life_base) if life_base != 0 else 0.0
    
    _52w = _rolling_52w_from_weekly_snapshot_pct()
    if _52w is not None:
        perf_52w_profit, perf_52w_pct = _52w
    else:
        perf_52w_profit, perf_52w_pct = 0.0, 0.0
# Summary table (%, US$, CA$)
    def _fmt_money(x): return f"${x:,.2f}"
    def _fmt_pct(x): return f"{x*100:.2f}%"

    summ_rows = [
        ("WTD", wtd_pct, wtd_profit, wtd_profit * fx),
        ("MTD", mtd_pct, mtd_profit, mtd_profit * fx),
        ("YTD", ytd_pct, ytd_profit, ytd_profit * fx),
        ("52W", perf_52w_pct, perf_52w_profit, perf_52w_profit * fx),
        ("Lifetime", life_pct, life_profit, life_profit * fx),
        ("FY Run Rate", fy_pct, fy_profit, fy_profit * fx),
    ]

    summ_html = "<table class='finance-table'><thead><tr><th>Profit/Loss</th><th>%</th><th>US$</th><th>CA$</th></tr></thead><tbody>"
    for lbl, pct, usd, cad in summ_rows:
        cls = "pos-val" if usd >= 0 else "neg-val"
        summ_html += f"<tr><td>{lbl}</td><td class='{cls}'>{_fmt_pct(pct)}</td><td class='{cls}'>{_fmt_money(usd)}</td><td class='{cls}'>{_fmt_money(cad)}</td></tr>"
    summ_html += "</tbody></table>"

    # --------------------------------------------------------------------------------
    # Portfolio Value table (keep same components, now show USD and CAD)
    # --------------------------------------------------------------------------------
    st.subheader("Portfolio Value")

    pv_rows = [
        ("Cash Balance", cash_usd, cash_usd * fx),
        ("Stock Equity", stock_value_usd, stock_value_usd * fx),
        ("LEAP Equity", leap_value_usd, leap_value_usd * fx),
        ("ITM Call Liability (Deducted)", -itm_liability_usd, -itm_liability_usd * fx),
    ]

    pv_html = "<table class='finance-table'><thead><tr><th>Component</th><th>US$</th><th>CA$</th></tr></thead><tbody>"
    for label, usd_v, cad_v in pv_rows:
        pv_html += f"<tr><td>{label}</td><td>{_fmt_money(usd_v)}</td><td>{_fmt_money(cad_v)}</td></tr>"
    pv_html += f"<tr class='total-row'><td>Total Portfolio Value</td><td>{_fmt_money(net_liq_usd)}</td><td>{_fmt_money(net_liq_cad)}</td></tr></tbody></table>"
    st.markdown(pv_html, unsafe_allow_html=True)

    st.subheader("Performance Summary (Excluding Deposits/Withdrawals)")
    st.markdown(summ_html, unsafe_allow_html=True)

    # --------------------------------------------------------------------------------
    # Keep the remainder of the dashboard identical to Option Details for now (tables + contract management)
    # --------------------------------------------------------------------------------
    st.divider()
    # Reuse the exact existing view by calling the duplicate page, but avoid double header.
    # We'll render the holdings + options tables by reusing the option_details_page logic, but skipping its header.
    # Easiest: inline-call by temporarily rendering a subheader marker and then executing the rest:
    # NOTE: option_details_page includes its own header; so we replicate the remaining sections minimally here.

    # --- Assets Display (USD) ---
    if not assets.empty:
        disp_assets = assets.copy()
        # Keep USD view in tables below
        stocks_df = disp_assets[disp_assets['type_norm'] == 'STOCK'].sort_values(by='symbol') if 'type_norm' in disp_assets.columns else disp_assets[disp_assets['type'] == 'STOCK'].sort_values(by='symbol')
        leaps_df = disp_assets[disp_assets['type_norm'] != 'STOCK'].sort_values(by='symbol') if 'type_norm' in disp_assets.columns else disp_assets[disp_assets['type'] != 'STOCK'].sort_values(by='symbol')
    else:
        stocks_df = pd.DataFrame()
        leaps_df = pd.DataFrame()

    
    # --- Total Holdings by Ticker (Stocks + Long LEAPS; Shorts shown as contracts only) ---
    st.subheader("Total Holdings")
    try:
        totals = {}

        # Stocks
        if not stocks_df.empty:
            tmp_s = stocks_df.copy()
            tmp_s['sym'] = tmp_s.get('symbol', tmp_s.get('ticker', 'UNK')).astype(str).str.upper().str.strip()
            tmp_s['shares'] = pd.to_numeric(tmp_s.get('quantity', 0), errors='coerce').fillna(0.0)
            tmp_s['stock_val'] = pd.to_numeric(tmp_s.get('market_value', 0), errors='coerce').fillna(0.0)

            for sym, g in tmp_s.groupby('sym'):
                totals.setdefault(sym, {"Ticker": sym, "Shares": 0.0, "Stock Value": 0.0,
                                       "LEAP Contracts": 0.0, "LEAP Value": 0.0,
                                       "Short Contracts": 0.0})
                totals[sym]["Shares"] += float(g['shares'].sum())
                totals[sym]["Stock Value"] += float(g['stock_val'].sum())

        # Long LEAPS (Options assets)
        if not leaps_df.empty:
            tmp_l = leaps_df.copy()
            tmp_l['sym'] = tmp_l.get('symbol', tmp_l.get('ticker', 'UNK')).astype(str).str.upper().str.strip()
            tmp_l['contracts'] = pd.to_numeric(tmp_l.get('quantity', 0), errors='coerce').fillna(0.0)
            tmp_l['px'] = pd.to_numeric(tmp_l.get('current_price', tmp_l.get('last_price', 0)), errors='coerce').fillna(0.0)
            tmp_l['leap_val'] = tmp_l['contracts'] * 100.0 * tmp_l['px']

            for sym, g in tmp_l.groupby('sym'):
                totals.setdefault(sym, {"Ticker": sym, "Shares": 0.0, "Stock Value": 0.0,
                                       "LEAP Contracts": 0.0, "LEAP Value": 0.0,
                                       "Short Contracts": 0.0})
                totals[sym]["LEAP Contracts"] += float(g['contracts'].sum())
                totals[sym]["LEAP Value"] += float(g['leap_val'].sum())

        # Short options (contracts only; ignore value)
        if grouped_options:
            by_sym_short = {}
            for r in grouped_options.values():
                sym = str(r.get('symbol', 'UNK')).upper().strip()
                by_sym_short[sym] = by_sym_short.get(sym, 0.0) + float(r.get('qty', 0.0) or 0.0)
            for sym, ct in by_sym_short.items():
                totals.setdefault(sym, {"Ticker": sym, "Shares": 0.0, "Stock Value": 0.0,
                                       "LEAP Contracts": 0.0, "LEAP Value": 0.0,
                                       "Short Contracts": 0.0})
                totals[sym]["Short Contracts"] += float(ct)

        if totals:
            out = pd.DataFrame(list(totals.values()))
            out["Total Market Value"] = out["Stock Value"] + out["LEAP Value"]

            denom = float(out["Total Market Value"].sum())
            if denom and denom != 0:
                out["% of Portfolio"] = out["Total Market Value"] / denom
            else:
                out["% of Portfolio"] = 0.0

            out = out.sort_values("Ticker")

            total_html = "<table class='finance-table'><thead><tr>" \
                         "<th>Ticker</th><th>Shares</th><th>Stock Value</th><th>LEAP Contracts</th><th>LEAP Value</th>" \
                         "<th>Short Contracts</th><th>Total Market Value</th><th>% of Portfolio</th></tr></thead><tbody>"

            for _, r in out.iterrows():
                total_html += (
                    f"<tr><td>{r['Ticker']}</td>"
                    f"<td>{float(r['Shares']):g}</td>"
                    f"<td>${float(r['Stock Value']):,.2f}</td>"
                    f"<td>{float(r['LEAP Contracts']):g}</td>"
                    f"<td>${float(r['LEAP Value']):,.2f}</td>"
                    f"<td>{float(r['Short Contracts']):g}</td>"
                    f"<td>${float(r['Total Market Value']):,.2f}</td>"
                    f"<td>{float(r['% of Portfolio'])*100:,.2f}%</td></tr>"
                )

            tot_shares = float(out["Shares"].sum())
            tot_stock = float(out["Stock Value"].sum())
            tot_leap_ct = float(out["LEAP Contracts"].sum())
            tot_leap_val = float(out["LEAP Value"].sum())
            tot_short_ct = float(out["Short Contracts"].sum())
            tot_mkt = float(out["Total Market Value"].sum())
            tot_pct = (tot_mkt / denom * 100.0) if denom else 0.0

            # Allocate Cash and ITM into Stock Value and LEAP Value, and show them as rows.
            # Per-ticker rows remain Stocks + LEAPs only (short value ignored).
            # We allocate Cash/ITM between Stock vs LEAP columns based on their invested weights.
            try:
                itm_val_raw = float(itm_liability_usd) if ('itm_liability_usd' in locals() or 'itm_liability_usd' in globals()) else 0.0
            except Exception:
                itm_val_raw = 0.0
            # ITM is a liability (deducted). Ensure it is negative in the table.
            itm_val = -abs(itm_val_raw) if itm_val_raw != 0 else 0.0

            try:
                cash_val = float(cash_usd) if ('cash_usd' in locals() or 'cash_usd' in globals()) else float(get_cash_balance(user_id))
            except Exception:
                try:
                    cash_val = float(get_cash_balance(user_id))
                except Exception:
                    cash_val = 0.0

            # Invested denominator (tickers only): used for allocation weights
            invested_val = float(tot_stock) + float(tot_leap_val)
            alloc_denom = invested_val if invested_val else 0.0
            w_stock = (float(tot_stock) / alloc_denom) if alloc_denom else 0.0
            w_leap = (float(tot_leap_val) / alloc_denom) if alloc_denom else 0.0

            # Allocate amounts into Stock/LEAP columns
            cash_stock = float(cash_val) * w_stock
            cash_leap = float(cash_val) * w_leap
            itm_stock = float(itm_val) * w_stock
            itm_leap = float(itm_val) * w_leap

            # Portfolio denominator for % column: tickers + cash + itm (still ignores short value)
            port_denom = invested_val + float(cash_val) + float(itm_val)
            if not port_denom:
                port_denom = invested_val  # fallback (avoid divide-by-zero if cash cancels itm)

            def _pct(v):
                try:
                    return (float(v) / float(port_denom) * 100.0) if port_denom else 0.0
                except Exception:
                    return 0.0

            # Add Cash row (same formatting as tickers)
            total_html += (
                f"<tr><td>Cash</td>"
                f"<td></td>"
                f"<td>${cash_stock:,.2f}</td>"
                f"<td></td>"
                f"<td>${cash_leap:,.2f}</td>"
                f"<td></td>"
                f"<td>${float(cash_val):,.2f}</td>"
                f"<td>{_pct(cash_val):,.2f}%</td></tr>"
            )

            # Add ITM row (same formatting as tickers)
            total_html += (
                f"<tr><td>ITM</td>"
                f"<td></td>"
                f"<td>${itm_stock:,.2f}</td>"
                f"<td></td>"
                f"<td>${itm_leap:,.2f}</td>"
                f"<td></td>"
                f"<td>${float(itm_val):,.2f}</td>"
                f"<td>{_pct(itm_val):,.2f}%</td></tr>"
            )

            # TOTAL row should be LAST, and should include Cash + ITM allocations
            tot_stock_adj = float(tot_stock) + cash_stock + itm_stock
            tot_leap_val_adj = float(tot_leap_val) + cash_leap + itm_leap
            tot_mkt_adj = invested_val + float(cash_val) + float(itm_val)

            total_html += (
                f"<tr class='total-row'><td>Total</td>"
                f"<td>{tot_shares:g}</td>"
                f"<td>${tot_stock_adj:,.2f}</td>"
                f"<td>{tot_leap_ct:g}</td>"
                f"<td>${tot_leap_val_adj:,.2f}</td>"
                f"<td>{tot_short_ct:g}</td>"
                f"<td>${tot_mkt_adj:,.2f}</td>"
                f"<td>{100.0:,.2f}%</td></tr>"
            )
            total_html += "</tbody></table>"
            st.markdown(total_html, unsafe_allow_html=True)
        else:
            st.info("No holdings to summarize.")
    except Exception as e:
        st.warning(f"Total Holdings summary unavailable: {e}")

    st.subheader("Stock Holdings (USD)")
    if not stocks_df.empty:
        stock_html = "<table class='finance-table'><thead><tr><th>Ticker</th><th>Qty</th><th>Avg Cost</th><th>Price</th><th>Market Value</th></tr></thead><tbody>"
        for _, row in stocks_df.iterrows():
            stock_html += f"<tr><td>{row.get('symbol','UNK')}</td><td>{float(row.get('quantity',0)):g}</td><td>${float(row.get('cost_basis',0)):,.2f}</td><td>${float(row.get('current_price',0)):,.2f}</td><td>${float(row.get('market_value',0)):,.2f}</td></tr>"
        stock_html += "</tbody></table>"
        st.markdown(stock_html, unsafe_allow_html=True)
    else:
        st.info("No Stock Holdings.")

    st.subheader("Long Options (LEAP) by Ticker (USD)")
    if not leaps_df.empty:
        # Consolidate contracts and value by ticker
        tmp = leaps_df.copy()
        tmp['sym'] = tmp.get('symbol', tmp.get('ticker', 'UNK')).astype(str).str.upper().str.strip()
        tmp['qty_num'] = pd.to_numeric(tmp.get('quantity', 0), errors='coerce').fillna(0)
        tmp['px_num'] = pd.to_numeric(tmp.get('current_price', tmp.get('last_price', 0)), errors='coerce').fillna(0)
        tmp['val_num'] = tmp['qty_num'] * 100.0 * tmp['px_num']

        grp = tmp.groupby('sym', as_index=False).agg(
            Contracts=('qty_num', 'sum'),
            Value=('val_num', 'sum'),
            AvgPrice=('px_num', lambda s: float(s.mean()) if len(s) else 0.0),
        )
        grp = grp.sort_values('sym')

        leap_html = "<table class='finance-table'><thead><tr><th>Ticker</th><th>Contracts</th><th>Avg Price</th><th>Value</th></tr></thead><tbody>"
        for _, r in grp.iterrows():
            leap_html += f"<tr><td>{r['sym']}</td><td>{float(r['Contracts']):g}</td><td>${float(r['AvgPrice']):,.2f}</td><td>${float(r['Value']):,.2f}</td></tr>"
        total_val = float(grp['Value'].sum()) if not grp.empty else 0.0
        total_ct = float(grp['Contracts'].sum()) if not grp.empty else 0.0
        leap_html += f"<tr class='total-row'><td>Total</td><td>{total_ct:g}</td><td></td><td>${total_val:,.2f}</td></tr>"
        leap_html += "</tbody></table>"
        st.markdown(leap_html, unsafe_allow_html=True)
    else:
        st.info("No Long Option Holdings.")

    # --- Short Options (Consolidated, USD) ---
    st.subheader("Short Options by Ticker (USD)")
    if grouped_options:
        rows = list(grouped_options.values())
        by_sym = {}
        for r in rows:
            sym = str(r.get('symbol', 'UNK')).upper().strip()
            if sym not in by_sym:
                by_sym[sym] = {
                    "symbol": sym,
                    "qty": 0.0,
                    "liability": 0.0,
                    "price": float(r.get('price', 0) or 0),
                    "covered": False
                }
            by_sym[sym]["qty"] += float(r.get('qty', 0) or 0)
            by_sym[sym]["liability"] += float(r.get('liability', 0) or 0)
            if r.get('linked_assets'):
                by_sym[sym]["covered"] = True

        final_display = list(by_sym.values())
        final_display.sort(key=lambda x: x['symbol'])

        opt_html = "<table class='finance-table'><thead><tr><th>Ticker</th><th>Contracts</th><th>Current Price</th><th>ITM Liability</th><th>Collateral</th></tr></thead><tbody>"
        for r in final_display:
            s_price = f"${r['price']:,.2f}" if r['price'] > 0 else "<span style='opacity:0.5'>0.00</span>"
            liab_raw = float(r['liability'])
            s_liab = f"${liab_raw:,.2f}"
            if liab_raw > 0:
                s_liab = f"<span class='liability-alert'>{s_liab}</span>"
            s_coll = "Covered" if r["covered"] else "<span style='color:#e67c73'>Unsecured</span>"
            opt_html += f"<tr><td>{r['symbol']}</td><td>{float(r['qty']):g}</td><td>{s_price}</td><td>{s_liab}</td><td>{s_coll}</td></tr>"
        total_qty = sum(float(r['qty']) for r in final_display)
        total_liab = sum(float(r['liability']) for r in final_display)
        opt_html += f"<tr class='total-row'><td>Total</td><td>{total_qty:g}</td><td></td><td>${total_liab:,.2f}</td><td></td></tr>"
        opt_html += "</tbody></table>"
        st.markdown(opt_html, unsafe_allow_html=True)
    else:
        st.info("No Active Short Options.")


def option_details_page(user):
    st.header("📊 Executive Dashboard")
    

    # Auto-refresh share/LEAP prices on page entry
    _auto_refresh_prices_on_enter(user, 'Option Details', also_force_leap_mid=False)
    # Manual refresh button
    if st.button("🔄 Refresh Prices", key=f"refresh_prices_{page_name}_{user.id}", type="primary"):
        st.cache_data.clear()
        st.rerun()

    # --- Top Controls ---
    c_ctrl_1, c_ctrl_2, c_ctrl_3 = st.columns([2, 4, 1])
    with c_ctrl_1:
        selected_currency = st.radio("Currency", ["USD", "CAD"], horizontal=True, label_visibility="collapsed")
    with c_ctrl_3:
        if st.button("🔄 Refresh Prices"):
            st.cache_data.clear()
            st.rerun()

    rate_multiplier = 1.0
    if selected_currency == "CAD":
        rate_multiplier = get_usd_to_cad_rate()
        st.caption(f"Exchange Rate: 1 USD = {rate_multiplier:.4f} CAD")
    
    # --- Data Loading ---
    cash_usd = get_cash_balance(user.id)
    assets, options = get_portfolio_data(user.id)
    # Normalize asset types to avoid case mismatches (e.g., 'stock' vs 'STOCK')
    try:
        if not assets.empty and 'type' in assets.columns:
            assets['type_norm'] = assets['type'].astype(str).str.upper().str.strip()
        else:
            assets['type_norm'] = 'STOCK'
    except Exception:
        assets['type_norm'] = 'STOCK'
    
    # --- Calculations ---
    stock_value_usd = 0.0
    leap_value_usd = 0.0
    itm_liability_usd = 0.0
    
    # 1. Assets Calculation
    if not assets.empty:
        for idx, row in assets.iterrows():
            qty = clean_number(row['quantity'])
            r_type_raw = str(row.get('type', '')).upper().strip()
            assets.at[idx, 'type_norm'] = r_type_raw
            r_type_disp = r_type_raw.replace('LONG_', 'LEAP ').replace('LEAP_', 'LEAP ')
            assets.at[idx, 'type_disp'] = r_type_disp
            
            if r_type_raw == 'STOCK':
                sym = str(row.get('symbol', '')).strip().upper()
                live_price = get_live_stock_price(sym)
                if live_price == 0: live_price = clean_number(row.get('last_price', 0))
                assets.at[idx, 'current_price'] = live_price
                assets.at[idx, 'market_value'] = qty * live_price
                stock_value_usd += (qty * live_price)
            else: 
                manual_price = clean_number(row.get('last_price', 0))
                assets.at[idx, 'current_price'] = manual_price
                assets.at[idx, 'market_value'] = qty * 100 * manual_price

    # Ensure LEAP Equity matches exactly what is shown in the LEAP table below
    # (sum of qty * 100 * current_price for all non-stock assets after pricing logic)
    try:
        leap_value_usd = 0.0
        if not assets.empty and 'type_norm' in assets.columns:
            non_stock = assets[assets['type_norm'] != 'STOCK'].copy()
            if not non_stock.empty:
                non_stock['qty_num'] = pd.to_numeric(non_stock.get('quantity', 0), errors='coerce').fillna(0)
                non_stock['px_num'] = pd.to_numeric(non_stock.get('current_price', non_stock.get('last_price', 0)), errors='coerce').fillna(0)
                leap_value_usd = float((non_stock['qty_num'] * 100.0 * non_stock['px_num']).sum())
    except Exception:
        leap_value_usd = 0.0

    # 2. Options Liability Calculation & Aggregation
    grouped_options = {}
    
    if not options.empty:
        for idx, row in options.iterrows():
            qty = abs(clean_number(row.get('quantity') or row.get('contracts') or 0))
            strike = float(clean_number(row.get('strike_price') or row.get('strike') or 0))
            sym = str(row.get('symbol', '')).strip().upper()
            opt_type = str(row.get('type', '')).strip().upper()
            
            # Robust Expiration Parsing (Prefer expiration_date; some rows may have incorrect 'expiration')
            raw_exp = row.get('expiration_date')
            if raw_exp is None or pd.isna(raw_exp) or str(raw_exp).strip() == "":
                raw_exp = row.get('expiration')
            exp_str = str(raw_exp) if raw_exp else ""
            
            underlying_price = get_live_stock_price(sym)
            
            intrinsic_val = 0.0
            if underlying_price > 0 and "CALL" in opt_type and underlying_price > strike:
                intrinsic_val = (underlying_price - strike) * qty * 100
            
            itm_liability_usd += intrinsic_val
            
            # --- Aggregation Logic ---
            key = (sym, opt_type, exp_str, strike)
            
            if key not in grouped_options:
                grouped_options[key] = {
                    'symbol': sym,
                    'type': opt_type,
                    'expiration': exp_str,
                    'strike': strike,
                    'qty': 0.0,
                    'price': underlying_price,
                    'liability': 0.0,
                    'constituents': [],
                    'linked_assets': []
                }
            
            grouped_options[key]['qty'] += qty
            grouped_options[key]['liability'] += intrinsic_val
            
            # Store full details for splitting logic
            old_premium = row.get('premium_received')
            if old_premium is None: old_premium = row.get('cost_basis', 0)
            
            lid = row.get('linked_asset_id')
            if lid and not pd.isna(lid):
                 grouped_options[key]['linked_assets'].append(str(lid))

            grouped_options[key]['constituents'].append({
                'id': row['id'],
                'qty': qty,
                'cost_basis': row.get('cost_basis', 0),
                'premium_received': old_premium,
                'open_date': row.get('open_date'),
                'linked_asset_id': lid
            })

    net_liq_usd = cash_usd + stock_value_usd + leap_value_usd - itm_liability_usd
    net_liq_disp = net_liq_usd * rate_multiplier

    # --- Display Portfolio Value ---
    st.subheader("Portfolio Value")
    pv_rows = [
        ("Cash Balance", f"${cash_usd * rate_multiplier:,.2f}"), 
        ("Stock Equity", f"${stock_value_usd * rate_multiplier:,.2f}"), 
        ("LEAP Equity", f"${leap_value_usd * rate_multiplier:,.2f}"), 
        ("ITM Call Liability (Deducted)", f"-${itm_liability_usd * rate_multiplier:,.2f}")
    ]
    
    pv_html = "<table class='finance-table'><thead><tr><th>Component</th><th>Amount</th></tr></thead><tbody>"
    for label, val in pv_rows: pv_html += f"<tr><td>{label}</td><td>{val}</td></tr>"
    pv_html += f"<tr class='total-row'><td>Total Portfolio Value</td><td>${net_liq_disp:,.2f}</td></tr></tbody></table>"
    st.markdown(pv_html, unsafe_allow_html=True)

    # --- Profit Analysis ---
    st.subheader("Total Profit & Analysis")
    baseline = get_baseline_snapshot(user.id)
    net_invested_cad = get_net_invested_cad(user.id)
    current_val_cad = net_liq_usd * get_usd_to_cad_rate()
    lifetime_pl_cad = current_val_cad - net_invested_cad
    lifetime_pl_pct = (lifetime_pl_cad / net_invested_cad) if net_invested_cad > 0 else 0
    cls_life = "pos-val" if lifetime_pl_cad >= 0 else "neg-val"
    
    prof_html = "<table class='finance-table'><thead><tr><th>Metric</th><th>Value</th></tr></thead><tbody>"
    prof_html += f"<tr><td><strong>Net Invested Capital (CAD)</strong></td><td><strong>${net_invested_cad:,.2f}</strong></td></tr>"
    prof_html += f"<tr><td><strong>Lifetime P/L (CAD)</strong></td><td class='{cls_life}'><strong>${lifetime_pl_cad:,.2f} ({lifetime_pl_pct*100:.2f}%)</strong></td></tr>"
    prof_html += "<tr><td colspan='2' style='background-color:#f0f2f6; text-align:center; font-size:0.85em; font-weight:bold;'>YTD Snapshot Analysis</td></tr>"

    if baseline:
        start_date_str = baseline['snapshot_date']; start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
        base_equity_usd = float(baseline['total_equity']); base_rate = float(baseline.get('exchange_rate', 1.0) or 1.0)
        start_val = base_equity_usd * base_rate if selected_currency == "CAD" else base_equity_usd
        profit_dollar = net_liq_disp - start_val; profit_pct = (profit_dollar / start_val) if start_val != 0 else 0
        today = date.today(); days_passed = (today - start_date).days; weeks_passed = days_passed / 7.0
        if days_passed < 1: days_passed = 1
        annualized_return = ((1 + profit_pct) ** (365.0 / days_passed)) - 1 if profit_pct > -1 else 0
        cls_ytd = "pos-val" if profit_dollar >= 0 else "neg-val"
        prof_html += f"<tr><td>Baseline Date (Start)</td><td>{start_date_str}</td></tr>"
        prof_html += f"<tr><td>Baseline Value</td><td>${start_val:,.2f}</td></tr>"
        prof_html += f"<tr><td>YTD Profit ($)</td><td class='{cls_ytd}'>${profit_dollar:,.2f}</td></tr>"
        prof_html += f"<tr><td>YTD Profit (%)</td><td class='{cls_ytd}'>{profit_pct*100:.2f}%</td></tr>"
        prof_html += f"<tr><td>FY Forecast (Annualized)</td><td>{annualized_return*100:.2f}%</td></tr>"
    else: prof_html += "<tr><td colspan='2'>No baseline snapshot found. Please create one.</td></tr>"
    prof_html += "</tbody></table>"
    st.markdown(prof_html, unsafe_allow_html=True)
    st.divider()

    # --- Assets Display ---
    if not assets.empty:
        disp_assets = assets.copy()
        for c in ['cost_basis', 'current_price', 'market_value', 'strike_price', 'strike']:
            if c in disp_assets.columns: disp_assets[c] = disp_assets[c].fillna(0) * rate_multiplier
        if 'type_norm' in disp_assets.columns:
            stocks_df = disp_assets[disp_assets['type_norm'] == 'STOCK'].sort_values(by='symbol')
            leaps_df = disp_assets[disp_assets['type_norm'] != 'STOCK'].sort_values(by='symbol')
        else:
            stocks_df = disp_assets[disp_assets['type'] == 'STOCK'].sort_values(by='symbol')
            leaps_df = disp_assets[disp_assets['type'] != 'STOCK'].sort_values(by='symbol')
    else: stocks_df = pd.DataFrame(); leaps_df = pd.DataFrame()

    st.subheader(f"Stock Holdings ({selected_currency})")
    if not stocks_df.empty:
        stock_html = "<table class='finance-table'><thead><tr><th>Ticker</th><th>Qty</th><th>Avg Cost</th><th>Price</th><th>Market Value</th></tr></thead><tbody>"
        for _, row in stocks_df.iterrows():
            stock_html += f"<tr><td>{row.get('symbol','UNK')}</td><td>{float(row.get('quantity',0)):g}</td><td>${float(row.get('cost_basis',0)):,.2f}</td><td>${float(row.get('current_price',0)):,.2f}</td><td>${float(row.get('market_value',0)):,.2f}</td></tr>"
        stock_html += "</tbody></table>"
        st.markdown(stock_html, unsafe_allow_html=True)
    else: st.info("No Stock Holdings.")

    st.subheader(f"Long Option (LEAP) Holdings ({selected_currency})")
    if not leaps_df.empty:
        leap_html = "<table class='finance-table'><thead><tr><th>Ticker</th><th>Type</th><th>Exp</th><th>Strike</th><th>Qty</th><th>Avg Cost</th><th>Price</th><th>Value</th></tr></thead><tbody>"
        for _, row in leaps_df.iterrows():
            leap_html += f"<tr><td>{row.get('symbol','UNK')}</td><td>{row.get('type_disp','').replace('LEAP','').strip()}</td><td>{format_date_custom(row.get('expiration',''))}</td><td>${float(row.get('strike_price',0)):,.2f}</td><td>{float(row.get('quantity',0)):g}</td><td>${float(row.get('cost_basis',0)):,.2f}</td><td>${float(row.get('current_price',0)):,.2f}</td><td>${float(row.get('market_value',0)):,.2f}</td></tr>"
        # Total row (must exactly match the per-line Value = current_price * qty * 100)
        try:
            qty_s = pd.to_numeric(leaps_df.get('quantity', 0), errors='coerce').fillna(0)
            px_s = pd.to_numeric(leaps_df.get('current_price', 0), errors='coerce').fillna(0)
            leap_total = float((qty_s * 100.0 * px_s).sum())
        except Exception:
            leap_total = 0.0
        leap_html += f"<tr class='total-row'><td colspan='7'>Total</td><td>${leap_total:,.2f}</td></tr>"
        leap_html += "</tbody></table>"
        st.markdown(leap_html, unsafe_allow_html=True)
    else: st.info("No Long Option Holdings.")

    # --- Short Options (Consolidated) ---
    st.subheader(f"Short Option Liabilities ({selected_currency})")
    
    if grouped_options:
        final_display_list = list(grouped_options.values())
        final_display_list.sort(key=lambda x: x['symbol'])
        
        opt_html = "<table class='finance-table'><thead><tr>"
        opt_html += "<th>Ticker</th><th>Type</th><th>Exp</th><th>Strike</th><th>Qty</th><th>Current Price</th><th>Liability</th><th>Collateral</th>"
        opt_html += "</tr></thead><tbody>"
        
        selector_options = {} 
        
        for row in final_display_list:
            s_strike = f"${row['strike'] * rate_multiplier:,.2f}"
            s_price = f"${row['price']:,.2f}" if row['price'] > 0 else "<span style='opacity:0.5'>0.00</span>"
            
            liab_raw = row['liability'] * rate_multiplier
            s_liab = f"${liab_raw:,.2f}"
            if liab_raw > 0:
                s_liab = f"<span class='liability-alert'>{s_liab}</span>"
            
            has_collateral = len(row['linked_assets']) > 0
            s_collateral = "Covered" if has_collateral else "<span style='color:#e67c73'>Unsecured</span>"
            s_date = format_date_custom(row['expiration'])
            
            opt_html += f"<tr><td>{row['symbol']}</td><td>{row['type']}</td><td>{s_date}</td>"
            opt_html += f"<td>{s_strike}</td><td>{row['qty']:g}</td><td>{s_price}</td><td>{s_liab}</td><td>{s_collateral}</td></tr>"
            
            label = f"{row['symbol']} {row['type']} ${row['strike']} ({s_date}) [Qty: {row['qty']:g}]"
            selector_options[label] = row

        opt_html += "</tbody></table>"
        st.markdown(opt_html, unsafe_allow_html=True)

        with st.expander("⚡ Manage Active Contracts", expanded=True):
            c_sel, c_act, c_btn = st.columns([3, 2, 1])
            with c_sel:
                selected_label = st.selectbox("Select Contract to Manage", options=list(selector_options.keys()), key="opt_man_sel")
            
            if selected_label:
                sel_row = selector_options[selected_label]
                total_avail = int(sel_row['qty'])
                
                with c_act:
                    action_choice = st.radio("Action", ["Assignment (Stock Trade)", "Expire (Close @ $0)", "Roll Position (Close & New)"], label_visibility="collapsed")
                
                # --- ROLL INPUTS ---
                qty_to_process = total_avail
                
                if "Roll" in action_choice:
                    st.markdown("---")
                    st.caption("🔄 **Roll Details**: Buy back current position and sell a new one.")
                    
                    r_c0, r_c1, r_c2, r_c3 = st.columns([1, 1, 1, 1])
                    with r_c0:
                        qty_to_process = st.number_input("Qty to Roll", min_value=1, max_value=total_avail, value=total_avail, step=1)
                    with r_c1:
                        btc_price = st.number_input("BTC Price ($)", min_value=0.0, format="%.2f", step=0.01)
                    with r_c2:
                        new_strike = st.number_input("New Strike ($)", value=float(sel_row['strike']), format="%.2f")
                    with r_c3:
                        new_premium = st.number_input("New Premium ($)", min_value=0.0, format="%.2f", step=0.01)
                    
                    def_date = datetime.now().date() + timedelta(days=30)
                    new_exp = st.date_input("New Expiration Date", value=def_date)

                    # Ensure standard float/int calculation (prevents numpy errors)
                    calc_btc = float(btc_price) * int(qty_to_process) * 100
                    calc_sto = float(new_premium) * int(qty_to_process) * 100
                    net_cash = calc_sto - calc_btc
                    st.write(f"**Net Cash Effect:** ${net_cash:+,.2f}")

                with c_btn:
                    st.write("")
                    st.write("") 
                    if st.button("Process Action", type="primary", use_container_width=True):
                        
                        # 1. ASSIGNMENT
                        if "Assignment" in action_choice:
                            # Group id for this multi-step transaction (used by Ledger)
                            txg = uuid.uuid4().hex[:12]

                            # Mark all constituent option rows as assigned
                            option_ids = []
                            for item in sel_row['constituents']:
                                option_ids.append(str(item['id']))
                                supabase.table("options").update({"status": "assigned"}).eq("id", item['id']).execute()

                            trade_date = date.today()
                            total_shares = sel_row['qty'] * 100

                            # 1) Ledger: expire the option (cash impact $0), include option ids for reliable rollback
                            formatted_exp = format_date_custom(_iso_date(sel_row['expiration']))
                            expire_desc = f"Expire {sel_row['type']} {sel_row['symbol']} {formatted_exp} ${float(sel_row['strike'])} (Assigned) OID:{','.join(option_ids)}"
                            log_transaction(user.id, expire_desc, 0.0, "OPTION_EXPIRE", sel_row['symbol'], trade_date, currency="USD", txg=txg)

                            # 2) Stock trade (Buy shares for PUT assignment / Sell shares for CALL assignment)
                            if sel_row['type'] == "PUT":
                                update_asset_position(user.id, sel_row['symbol'], total_shares, sel_row['strike'], "Buy", trade_date, "STOCK", txg=txg)
                                st.success(f"Assigned on PUT. Bought {total_shares} shares.")
                            elif sel_row['type'] == "CALL":
                                update_asset_position(user.id, sel_row['symbol'], total_shares, sel_row['strike'], "Sell", trade_date, "STOCK", txg=txg)
                                st.success(f"Assigned on CALL. Sold {total_shares} shares.")

                            st.cache_data.clear()
                            st.rerun()
                                
                        # 2. EXPIRE
                        elif "Expire" in action_choice:
                            remaining_needed = qty_to_process
                            for item in sel_row['constituents']:
                                if remaining_needed <= 0: break
                                row_qty = int(item['qty'])
                                
                                if row_qty <= remaining_needed:
                                    supabase.table("options").update({
                                        "status": "expired", 
                                        "closing_price": 0.0,
                                        "closed_date": datetime.now().isoformat()
                                    }).eq("id", item['id']).execute()
                                    remaining_needed -= row_qty
                                else:
                                    # SPLIT
                                    new_rem_qty = row_qty - remaining_needed
                                    old_prem = item.get('premium_received') or item.get('cost_basis') or 0.0
                                    
                                    supabase.table("options").update({"quantity": new_rem_qty, "contracts": new_rem_qty}).eq("id", item['id']).execute()
                                    
                                    supabase.table("options").insert({
                                        "user_id": user.id, "symbol": sel_row['symbol'], "ticker": sel_row['symbol'], "type": sel_row['type'],
                                        "strike_price": sel_row['strike'], "expiration_date": sel_row['expiration'], "quantity": remaining_needed, "contracts": remaining_needed,
                                        "status": "expired", "cost_basis": item['cost_basis'], "premium_received": old_prem, "open_date": item['open_date'],
                                        "closing_price": 0.0, "closed_date": datetime.now().isoformat()
                                    }).execute()
                                    remaining_needed = 0

                            st.success(f"Contracts expired/cancelled at $0.00.")
                            st.cache_data.clear()
                            st.rerun()

                        # 3. ROLL (BTC then STO; both write to ledger via update_short_option_position)
                        elif "Roll" in action_choice:
                            qty_safe = int(qty_to_process)

                            # Inherit Linked Asset (for covered calls / linked collateral)
                            inherited_link_id = None
                            if 'linked_assets' in sel_row and sel_row['linked_assets']:
                                inherited_link_id = sel_row['linked_assets'][0]
                            if not inherited_link_id:
                                for c in sel_row['constituents']:
                                    if c.get('linked_asset_id'):
                                        inherited_link_id = c['linked_asset_id']
                                        break

                            txn_date_today = date.today()
                            txg = uuid.uuid4().hex[:12]

                            # A) BTC: Buy-to-close existing contract(s) -> logs negative cash impact
                            update_short_option_position(
                                user.id,
                                sel_row['symbol'],
                                qty_safe,
                                float(btc_price),
                                "Buy",
                                txn_date_today,
                                sel_row['type'],
                                sel_row['expiration'],
                                float(sel_row['strike']),
                                fees=0.0,
                                txg=txg
                            )

                            # B) STO: Sell-to-open new contract -> logs positive cash impact
                            update_short_option_position(
                                user.id,
                                sel_row['symbol'],
                                qty_safe,
                                float(new_premium),
                                "Sell",
                                txn_date_today,
                                sel_row['type'],
                                new_exp,
                                float(new_strike),
                                fees=0.0,
                                linked_asset_id_override=inherited_link_id,
                                txg=txg
                            )

                            st.success(f"Rolled {qty_safe} contracts. Net Cash: ${(float(new_premium) - float(btc_price)) * qty_safe * 100:+,.2f}")
                            st.cache_data.clear()
                            st.rerun()

    else: st.info("No Active Short Options.")

def snapshot_page(user):
    st.header("📸 Weekly Snapshot & History")
    tab_snap, tab_hist = st.tabs(["Create Snapshot", "History Graph"])
    
    with tab_snap:
        st.write("Freeze your portfolio value every Friday or Dec 31st.")
        freeze_date = st.date_input("Select Freeze Date", value=date.today())
        if not ((freeze_date.weekday() == 4) or (freeze_date.month == 12 and freeze_date.day == 31)): 
            st.warning("⚠️ Please select a Friday or December 31st.")
        else:
            st.divider()
            val_input = st.number_input("Total Value (USD)", value=float(get_net_liquidation_usd(user.id)), step=100.0, format="%.2f")
            rate_input = st.number_input("USD/CAD Rate", value=float(get_usd_to_cad_rate()), step=0.0001, format="%.4f")
            if st.button("Confirm Freeze", type="primary"): 
                capture_snapshot(user.id, val_input, rate_input, freeze_date)
                st.success(f"Snapshot for {freeze_date} saved.")
    
    with tab_hist:
        hist_df = get_portfolio_history(user.id)
        if not hist_df.empty:
            st.subheader("Portfolio Performance Trend")
            
            # 1. Prepare Date & Value
            hist_df['snapshot_date'] = pd.to_datetime(hist_df['snapshot_date'])
            hist_df = hist_df.sort_values('snapshot_date', ascending=True) 

            # 2. Fetch Transactions for Calculations
            tx_res = supabase.table("transactions").select("transaction_date, amount, type, currency").eq("user_id", user.id).in_("type", ["DEPOSIT", "WITHDRAWAL"]).execute()
            tx_df = pd.DataFrame(tx_res.data)
            if not tx_df.empty:
                tx_df['transaction_date'] = pd.to_datetime(tx_df['transaction_date'])
                tx_df = tx_df[tx_df['currency'] == 'USD']
            
            # 3. Calculate Table Metrics
            table_data = []
            for i in range(len(hist_df)):
                row = hist_df.iloc[i]
                curr_date = row['snapshot_date']
                curr_eq = float(row['total_equity'])

                # --- A. Previous Snapshot ---
                if i == 0:
                    prev_date = pd.Timestamp.min
                    prev_eq = 0.0
                else:
                    prev_row = hist_df.iloc[i-1]
                    prev_date = prev_row['snapshot_date']
                    prev_eq = float(prev_row['total_equity'])

                # --- B. Net Deposits/Withdrawals during the week (normalize returns) ---
                net_flow = 0.0
                if not tx_df.empty:
                    mask = (tx_df['transaction_date'] > prev_date) & (tx_df['transaction_date'] <= curr_date)
                    net_flow = float(tx_df.loc[mask, 'amount'].sum())  # deposits positive, withdrawals negative

                # --- C. Weekly Profit $ and Weekly Return % (normalized for flows) ---
                base_capital = prev_eq + net_flow
                weekly_profit = curr_eq - base_capital

                if i == 0 or base_capital == 0:
                    weekly_ret = 0.0
                else:
                    weekly_ret = weekly_profit / base_capital  # decimal (0.0123 = 1.23%)

                table_data.append({
                    "Date": curr_date.strftime('%Y-%m-%d'),
                    "Equity": curr_eq,
                    "Net Dep": net_flow,
                    "P/L $": weekly_profit,
                    "Weekly %": weekly_ret,
                })

            # --- D. Compute YTD compound return, weekly compound average (YTD), and 52W rolling compound ---
            calc_df = pd.DataFrame(table_data)

            ytd_vals = []
            wkly_avg_vals = []
            roll_52_vals = []

            for i in range(len(calc_df)):
                d = pd.to_datetime(calc_df.loc[i, "Date"]).date()
                yr = d.year

                # YTD weekly returns: include weekly returns for rows in same year up to i (excluding row 0)
                year_idx = [k for k in range(len(calc_df)) if pd.to_datetime(calc_df.loc[k, "Date"]).date().year == yr and k <= i]
                year_rets = [float(calc_df.loc[k, "Weekly %"]) for k in year_idx if k > 0]

                ytd_prod = 1.0
                for r in year_rets:
                    ytd_prod *= (1.0 + r)
                ytd_ret = (ytd_prod - 1.0) if year_rets else 0.0
                ytd_vals.append(ytd_ret)

                n_weeks = len(year_rets)
                wkly_avg = (1.0 + ytd_ret) ** (1.0 / n_weeks) - 1.0 if n_weeks > 0 else 0.0
                wkly_avg_vals.append(wkly_avg)

                # 52W rolling window: last 52 weekly returns ending at i (or since inception)
                start_k = max(1, i - 51)
                window_rets = [float(calc_df.loc[k, "Weekly %"]) for k in range(start_k, i + 1) if k > 0]

                roll_prod = 1.0
                for r in window_rets:
                    roll_prod *= (1.0 + r)
                roll_ret = (roll_prod - 1.0) if window_rets else 0.0
                roll_52_vals.append(roll_ret)

            calc_df["YTD %"] = ytd_vals
            calc_df["Wkly Avg %"] = wkly_avg_vals
            calc_df["52W %"] = roll_52_vals

            final_df = calc_df.iloc[::-1].copy()

            # --- CUSTOM PANDAS STYLING ---
            # This is the robust way to handle -$1,234.56 format while keeping right alignment
            def currency_fmt(x):
                if pd.isna(x): return "$0.00"
                return f"-${abs(x):,.2f}" if x < 0 else f"${x:,.2f}"

            def pct_fmt(x):
                return f"{x*100:.2f}%"

            # Apply formatting to specific columns
            # note: We use st.column_config to rename headers, but style to format values
            styled_df = final_df.style.format({
                "Equity": currency_fmt,
                "Net Dep": currency_fmt,
                "P/L $": currency_fmt,
                "Weekly %": pct_fmt,
                "YTD %": pct_fmt,
                "Wkly Avg %": pct_fmt,
                "52W %": pct_fmt
            })

            st.dataframe(
                styled_df,
                column_config={
                    "Date": st.column_config.TextColumn("Snapshot Date"),
                    "Equity": st.column_config.Column("Total Equity (USD)"),
                    "Net Dep": st.column_config.Column("Net Deposits", help="Net Deposits/Withdrawals since last snapshot"),
                    "P/L $": st.column_config.Column("Profit/Loss $"),
                    "Weekly %": st.column_config.Column("Weekly %", help="Weekly return = Weekly Profit / (Last Week Close + Net Deposits This Week)"),
                    "YTD %": st.column_config.Column("YTD %"),
                    "Wkly Avg %": st.column_config.Column("Wkly Avg %", help="Compounded Weekly Growth Rate (YTD since Jan 1)"),
                    "52W %": st.column_config.Column("52W %", help="Rolling 52-week return (excluding deposits)"),
                },
                hide_index=True,
                use_container_width=True
            )
            st.divider()
            st.subheader("Portfolio Performance Trend")

            chart_df = hist_df.copy()
            chart_df['snapshot_date'] = pd.to_datetime(chart_df['snapshot_date'])
            chart_df = chart_df.sort_values('snapshot_date', ascending=True)

            if 'exchange_rate' in chart_df.columns:
                chart_df['value_cad'] = chart_df['total_equity'] * chart_df['exchange_rate'].fillna(1.0)
            else:
                chart_df['value_cad'] = chart_df['total_equity'] * get_usd_to_cad_rate()

            # Mark deposit weeks (net deposits between snapshots > 0)
            dep_marks = pd.DataFrame(table_data)
            if not dep_marks.empty:
                dep_marks['snapshot_date'] = pd.to_datetime(dep_marks['Date'])
                dep_marks = dep_marks[dep_marks['Net Dep'] > 0][['snapshot_date', 'Net Dep']]
            else:
                dep_marks = pd.DataFrame(columns=['snapshot_date', 'Net Dep'])

            base = alt.Chart(chart_df).encode(
                x=alt.X('snapshot_date:T', title='Date')
            )

            line = base.mark_line().encode(
                y=alt.Y('value_cad:Q', title='Portfolio Value (CAD)')
            )

            points = alt.Chart(dep_marks).mark_point(size=80).encode(
                x=alt.X('snapshot_date:T'),
                y=alt.Y('Net Dep:Q', title=None),
                tooltip=[alt.Tooltip('snapshot_date:T', title='Date'), alt.Tooltip('Net Dep:Q', title='Deposit (USD)', format=',.2f')]
            ).transform_calculate(
                # place marker near the line using chart_df value is complex; instead use a rule
                dummy='0'
            )

            rules = alt.Chart(dep_marks).mark_rule(strokeDash=[4,4]).encode(
                x=alt.X('snapshot_date:T'),
                tooltip=[alt.Tooltip('snapshot_date:T', title='Date'), alt.Tooltip('Net Dep:Q', title='Deposit (USD)', format=',.2f')]
            )

            chart = (line + rules).properties(height=320)
            st.altair_chart(chart, use_container_width=True)


        else: st.info("No snapshots recorded yet.")

def import_page(user):
    st.header("📂 Bulk Data Import")
    st.info("Upload CSV files to populate your portfolio history.")
    
    # ADDED "6. Unified Import" to the tabs list
    tab_st, tab_leap, tab_opt, tab_cash, tab_hist, tab_unified = st.tabs([
        "1. Stocks", "2. LEAPS", "3. Short Options", "4. Cash", "5. History", "6. ✨ Unified Import"
    ])
    
    # --- Helpers ---
    def get_fees(row):
        for k in ['commission', 'comm', 'fee', 'fees']:
            if k in row: return abs(clean_number(row[k]))
        return 0.0

    def clean_action_input(val):
        if pd.isna(val) or val == "": return "Buy"
        return str(val).strip().title()

    def normalize_trade_action(val, default="Buy"):
        """Map messy broker actions to 'Buy' or 'Sell'.
        Handles: BUY/SELL, BTO/BTC/STO/STC, 'BUY TO OPEN/CLOSE', 'SELL TO OPEN/CLOSE'.
        """
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return default
        s = str(val).strip().upper()

        # Common option abbreviations
        if "STO" in s or "SELL TO OPEN" in s:
            return "Sell"
        if "BTC" in s or "BUY TO CLOSE" in s:
            return "Buy"
        if "BTO" in s or "BUY TO OPEN" in s:
            return "Buy"
        if "STC" in s or "SELL TO CLOSE" in s:
            return "Sell"

        # Generic
        if "SELL" in s:
            return "Sell"
        if "BUY" in s:
            return "Buy"
        return default
        s = str(val).strip().upper()
        if "SELL" in s:
            return "Sell"
        if "BUY" in s:
            return "Buy"
        return default

    def normalize_symbol(val):
        """Normalize symbols like 'SPDR Gold (ARCX:GLD)' or 'ARCX:GLD' to 'GLD'."""
        if val is None:
            return ""
        s = str(val).strip()
        # If 'Name (ARCX:GLD)' take inside parentheses
        m = re.search(r"\((.*?)\)", s)
        if m:
            s = m.group(1)
        # If 'ARCX:GLD' take part after ':'
        if ":" in s:
            s = s.split(":")[-1]
        return s.strip().upper()

    def normalize_expiration(val):
        """Normalize expiration input to YYYY-MM-DD string."""
        if val is None or (isinstance(val, float) and pd.isna(val)) or str(val).strip() == "":
            return ""
        try:
            dt = pd.to_datetime(val, errors="coerce")
            if pd.isna(dt):
                return str(val).split("T")[0]
            return dt.date().isoformat()
        except Exception:
            return str(val).split("T")[0]

    # --- 1. STOCKS ---
    with tab_st:
        st.markdown("**Required:** `Date`, `Ticker`, `Qty`, `Price`, `Action`. **Optional:** `Fees`")
        f_st = st.file_uploader("Upload Stocks CSV", type="csv", key="up_st")
        
        if f_st and st.button("Process Stocks"):
            try:
                df = pd.read_csv(f_st)
                df.columns = [c.strip().lower() for c in df.columns]
                rename_map = {'quantity': 'qty', 'shares': 'qty', 'symbol': 'ticker', 'stock': 'ticker', 'cost': 'price', 'rate': 'price', 'commission': 'fees', 'comm': 'fees'}
                df.rename(columns=rename_map, inplace=True)
                df['date_parsed'] = pd.to_datetime(df['date'], errors='coerce')
                
                count = 0
                for _, row in df[df['date_parsed'].notna()].iterrows():
                    qty = abs(clean_number(row.get('qty', 0)))
                    try: raw_p = str(row.get('price', 0)).replace('$','').replace(',','').strip(); price = abs(float(raw_p)) 
                    except: price = 0.0
                    fees = get_fees(row)
                    final_action = clean_action_input(row.get('action', 'Buy'))
                    
                    update_asset_position(user.id, str(row.get('ticker','')).upper(), qty, price, final_action, row['date_parsed'].date(), "STOCK", fees=fees)
                    count += 1
                st.success(f"Processed {count} stock transactions.")
            except Exception as e: st.error(f"Error: {e}")

    # --- 2. LEAPS ---
    with tab_leap:
        st.markdown("**Required:** `Date`, `Ticker`, `Qty`, `Price`, `Action`, `Type`, `Exp`, `Strike`. **Optional:** `Fees`")
        f_lp = st.file_uploader("Upload LEAPS CSV", type="csv", key="up_lp")
        
        if f_lp and st.button("Process LEAPS"):
            try:
                df = pd.read_csv(f_lp)
                df.columns = [c.strip().lower() for c in df.columns]
                rename_map = {'quantity': 'qty', 'contracts': 'qty', 'symbol': 'ticker', 'stock': 'ticker', 'cost': 'price', 'premium': 'price', 'commission': 'fees', 'comm': 'fees', 'expiration_date': 'expiration', 'expiry': 'expiration', 'exp': 'expiration', 'strike_price': 'strike', 'option type': 'type', 'option_type': 'type', 'opt_type': 'type', 'right': 'type', 'put/call': 'type', 'call/put': 'type'}
                df.rename(columns=rename_map, inplace=True)
                df['date_parsed'] = pd.to_datetime(df['date'], errors='coerce')
                
                count = 0
                for _, row in df[df['date_parsed'].notna()].iterrows():
                    qty = abs(int(clean_number(row.get('qty', 0))))
                    price = abs(clean_number(row.get('price', 0)))
                    strike = abs(clean_number(row.get('strike', 0)))
                    fees = get_fees(row)
                    final_action = clean_action_input(row.get('action', 'Buy'))
                    l_type = str(row.get('type', 'CALL')).strip().upper()
                    
                    update_asset_position(user.id, str(row.get('ticker','')).upper(), qty, price, final_action, row['date_parsed'].date(), f"LEAP_{l_type}", row.get('expiration'), strike, fees=fees)
                    count += 1
                st.success(f"Processed {count} LEAP transactions.")
            except Exception as e: st.error(f"Error: {e}")

    # --- 3. SHORT OPTIONS ---
    with tab_opt:
        st.markdown("**Required:** `Date`, `Ticker`, `Qty`, `Price`, `Action`, `Type`, `Exp`, `Strike`. **Optional:** `Fees`")
        f_op = st.file_uploader("Upload Options CSV", type="csv", key="up_op")
        
        if f_op and st.button("Process Shorts"):
            try:
                df = pd.read_csv(f_op)
                df.columns = [c.strip().lower() for c in df.columns]
                rename_map = {'quantity': 'qty', 'contracts': 'qty', 'symbol': 'ticker', 'stock': 'ticker', 'cost': 'price', 'premium': 'price', 'commission': 'fees', 'comm': 'fees', 'expiration_date': 'expiration', 'expiry': 'expiration', 'exp': 'expiration', 'strike_price': 'strike', 'option type': 'type', 'option_type': 'type', 'opt_type': 'type', 'right': 'type', 'put/call': 'type', 'call/put': 'type'}
                df.rename(columns=rename_map, inplace=True)
                df['date_parsed'] = pd.to_datetime(df['date'], errors='coerce')
                
                count = 0
                for _, row in df[df['date_parsed'].notna()].iterrows():
                    qty = abs(int(clean_number(row.get('qty', 0))))
                    price = abs(clean_number(row.get('price', 0)))
                    strike = abs(clean_number(row.get('strike', 0)))
                    fees = get_fees(row)
                    final_action = clean_action_input(row.get('action', 'Sell'))
                    
                    update_short_option_position(user.id, str(row.get('ticker','')).upper(), qty, price, final_action, row['date_parsed'].date(), str(row.get('type', 'PUT')).strip().upper(), row.get('expiration'), strike, fees=fees)
                    count += 1
                st.success(f"Processed {count} short option transactions.")
            except Exception as e: st.error(f"Error: {e}")
    
    # --- 4. CASH ---
    with tab_cash:
        st.subheader("Import Cash (Multi-Currency Columns)")
        cash_file = st.file_uploader("Upload CSV", type=["csv"], key="cash_up_multi")
        if cash_file:
            df = pd.read_csv(cash_file)
            all_cols = df.columns.tolist()
            def find_idx(options, columns):
                for opt in options:
                    for i, col in enumerate(columns):
                        if opt.lower() in col.lower(): return i
                return 0
            c1, c2, c3 = st.columns(3)
            col_date = c1.selectbox("Date Column", all_cols, index=find_idx(['date', 'time'], all_cols))
            col_type = c2.selectbox("Type/Action Column", all_cols, index=find_idx(['type', 'action'], all_cols))
            col_desc = c3.selectbox("Description Column", all_cols, index=find_idx(['desc', 'memo', 'note'], all_cols))
            c4, c5 = st.columns(2)
            col_options = ["-- None --"] + all_cols
            col_usd = c4.selectbox("USD Amount Column", col_options, index=find_idx(['usd', 'u.s.'], all_cols) + 1) 
            col_cad = c5.selectbox("CAD Amount Column", col_options, index=find_idx(['cad', 'can'], all_cols) + 1)
            
            if st.button("Process Transactions", type="primary"):
                success_count = 0
                for idx, row in df.iterrows():
                    try:
                        try: t_date = pd.to_datetime(str(row[col_date])).date()
                        except: t_date = date.today()
                        raw_type = str(row[col_type]).upper(); description = str(row.get(col_desc, 'Imported Tx'))
                        multiplier = 1; db_type = "DEPOSIT"
                        
                        if any(x in raw_type for x in ["WITHDRAW", "DEBIT", "PAYMENT"]): db_type = "WITHDRAWAL"; multiplier = -1
                        elif "FEE" in raw_type: db_type = "FEES"; multiplier = -1
                        elif "DIVIDEND" in raw_type: db_type = "DIVIDEND"; multiplier = 1 
                        elif "INTEREST" in raw_type:
                            db_type = "INTEREST"
                            if any(x in raw_type for x in ["PAID", "EXPENSE"]): multiplier = -1
                            else: multiplier = 1
                        elif any(x in raw_type for x in ["DEPOSIT", "CREDIT"]): db_type = "DEPOSIT"; multiplier = 1

                        if col_usd != "-- None --":
                            amt = abs(clean_number(row.get(col_usd, 0)))
                            if amt > 0: supabase.table("transactions").insert({"user_id": user.id, "transaction_date": t_date.isoformat(), "type": db_type, "amount": amt * multiplier, "currency": "USD", "related_symbol": "CASH", "description": f"{description} ({raw_type})"}).execute(); success_count += 1
                        if col_cad != "-- None --":
                            amt = abs(clean_number(row.get(col_cad, 0)))
                            if amt > 0: supabase.table("transactions").insert({"user_id": user.id, "transaction_date": t_date.isoformat(), "type": db_type, "amount": amt * multiplier, "currency": "CAD", "related_symbol": "CASH", "description": f"{description} ({raw_type})"}).execute(); success_count += 1
                    except: pass
                st.success(f"Processing Complete! Imported {success_count} transactions.")

    # --- 5. HISTORY ---
    with tab_hist:
        st.markdown("**Required Columns:** `Date`, `USD Value`, `FX Rate`")
        f_hist = st.file_uploader("Upload History CSV", type="csv", key="up_hist")
        if f_hist and st.button("Process History"):
            try:
                df = pd.read_csv(f_hist); df.columns = [c.strip().lower() for c in df.columns]; df['date_parsed'] = pd.to_datetime(df['date'], errors='coerce')
                count = 0
                for _, row in df[df['date_parsed'].notna()].iterrows():
                    capture_snapshot(user.id, clean_number(row['usd value']), clean_number(row['fx rate']), row['date_parsed'].date())
                    count += 1
                st.success(f"Processed {count} snapshots.")
            except Exception as e: st.error(f"Error: {e}")

    # --- 6. UNIFIED IMPORT (NEW) ---
    with tab_unified:
        st.markdown("### ✨ Unified Transaction Import")
        st.markdown("""
        **Process everything in one file to ensure perfect chronological order.**  
        Upload a single CSV containing Stocks, LEAPS, Short Options, and Cash Transfers.
        
        **Required Columns:** `Date`, `Category`, `Action`, `Symbol`, `Qty`, `Price`  
        **Conditional Columns:** `Strike`, `Expiration` (for Options), `Option Type` (Call/Put), `Fees`
        
        **Supported Categories (Case Insensitive):**
        - `STOCK` (Shares)
        - `LEAP` (Long Options)
        - `SHORT OPTION` or `OPTION` (Short Liabilities)
        - `CASH` (Deposits, Withdrawals, Dividends)
        """)
        
        f_uni = st.file_uploader("Upload Master CSV", type="csv", key="up_unified")
        
        if f_uni and st.button("Process Unified File", type="primary"):
            try:
                df = pd.read_csv(f_uni)
                df.columns = [c.strip().lower() for c in df.columns]
                
                # 1. Normalize Columns
                rename_map = {
                    'quantity': 'qty', 'shares': 'qty', 'contracts': 'qty',
                    'symbol': 'ticker', 'stock': 'ticker',
                    'cost': 'price', 'premium': 'price', 'amount': 'price',
                    'commission': 'fees', 'comm': 'fees',
                    'expiration_date': 'expiration', 'expiry': 'expiration', 'exp': 'expiration',
                    'strike_price': 'strike',
                    'type': 'category', 'class': 'category',  # Map 'Type' to Category
                    'option_type': 'opt_type', 'option type': 'opt_type', 'opt_type': 'opt_type',
                    'right': 'opt_type', 'put/call': 'opt_type', 'call/put': 'opt_type'  # Call/Put
                }
                # Be careful not to overwrite 'type' if it refers to Call/Put vs Asset Class
                # Heuristic: If 'category' column exists, use it. If not, look for 'class'.
                df.rename(columns=rename_map, inplace=True)
                
                # 2. Date Parsing & Sorting (CRITICAL STEP)
                # Preserve file row order for same-day trades (prevents Buy being processed before Sell)
                df['_row_order'] = range(len(df))
                df['date_parsed'] = pd.to_datetime(df['date'], errors='coerce')
                df.sort_values(by=['date_parsed', '_row_order'], ascending=[True, True], inplace=True)
                
                count = 0
                errors = []
                bar = st.progress(0)
                
                for i, row in enumerate(df.iterrows()):
                    idx, r = row
                    if pd.isna(r['date_parsed']): continue
                    
                    try:
                        # Extract Common Fields
                        cat = str(r.get('category', '')).upper().strip()
                        # Fallback if user put "Call" in the Category column for a LEAP
                        if 'LEAP' in cat: cat_mode = 'LEAP'
                        elif 'SHORT' in cat or 'OPTION' in cat: cat_mode = 'SHORT'
                        elif 'STOCK' in cat: cat_mode = 'STOCK'
                        elif 'CASH' in cat or 'FUND' in cat: cat_mode = 'CASH'
                        else: cat_mode = 'STOCK' # Default
                        
                        sym = normalize_symbol(r.get('ticker',''))
                        qty = int(abs(clean_number(r.get('qty', 0))))
                        
                        # Price cleaning
                        try: raw_p = str(r.get('price', 0)).replace('$','').replace(',','').strip(); price = abs(float(raw_p)) 
                        except: price = 0.0
                        
                        fees = get_fees(r)
                        act = normalize_trade_action(r.get('action', 'Buy'), default='Buy')
                        
                        # Specific Fields
                        opt_type = str(r.get('opt_type', 'CALL')).strip().upper()  # Call/Put
                        strike = float(abs(clean_number(r.get('strike', 0))))
                        exp = normalize_expiration(r.get('expiration'))
                        
                        # --- ROUTING LOGIC ---
                        if cat_mode == 'STOCK':
                            update_asset_position(user.id, sym, qty, price, act, r['date_parsed'].date(), "STOCK", fees=fees)
                            
                        elif cat_mode == 'LEAP':
                            # Asset Logic
                            a_type = f"LEAP_{opt_type}" # LEAP_CALL or LEAP_PUT
                            update_asset_position(user.id, sym, qty, price, act, r['date_parsed'].date(), a_type, exp, strike, fees=fees)
                            
                        elif cat_mode == 'SHORT':
                            # Liability Logic
                            # Default short options to PUT if undefined, but user should specify
                            if opt_type not in ['CALL', 'PUT']: opt_type = 'PUT'
                            update_short_option_position(user.id, sym, qty, price, act, r['date_parsed'].date(), opt_type, exp, strike, fees=fees)
                            
                        elif cat_mode == 'CASH':
                            # Direct Transaction Insert
                            # Determine Type
                            raw_act = str(r.get('action','')).upper()
                            db_type = "DEPOSIT"
                            mult = 1
                            
                            if any(x in raw_act for x in ["WITHDRAW", "DEBIT"]): db_type = "WITHDRAWAL"; mult = -1
                            elif "DIVIDEND" in raw_act: db_type = "DIVIDEND"; mult = 1
                            elif "INTEREST" in raw_act: db_type = "INTEREST"; mult = 1
                            elif "FEE" in raw_act: db_type = "FEES"; mult = -1
                            
                            supabase.table("transactions").insert({
                                "user_id": user.id,
                                "transaction_date": r['date_parsed'].isoformat(),
                                "type": db_type,
                                "amount": price * mult, # Assuming 'Price' column holds the cash amount
                                "currency": "USD", # Default to USD for unified
                                "related_symbol": "CASH",
                                "description": f"Unified Import: {raw_act}"
                            }).execute()
                            
                        count += 1
                        
                    except Exception as inner_e:
                        errors.append(f"Row {idx}: {inner_e}")
                    
                    bar.progress((i + 1) / len(df))

                st.success(f"✅ Successfully processed {count} records in chronological order.")
                if errors:
                    with st.expander(f"⚠️ {len(errors)} Errors Occurred"):
                        for e in errors: st.write(e)
                        
            except Exception as e: st.error(f"Critical Error reading file: {e}")

def cash_management_page(user):
    st.header("💸 Cash Management")
    c1, c2 = st.columns(2)
    with c1:
        txn_type = st.selectbox("Transaction Type", ["Deposit", "Withdrawal", "Dividend", "Interest (Received)", "Interest (Paid)"])
        amt_usd = st.number_input("Amount (USD)", min_value=0.01, step=10.0)
        amt_cad = st.number_input("Amount (CAD Equivalent)", min_value=0.01, step=10.0) if txn_type in ["Deposit", "Withdrawal"] else 0.0
    with c2:
        txn_date = st.date_input("Date", value=date.today())
        rel_sym = st.text_input("Related Ticker (Optional)", placeholder="e.g. USD").upper() or "USD"
    
    if st.button("Process Transaction", type="primary"):
        f_usd = -amt_usd if txn_type in ["Withdrawal", "Interest (Paid)"] else amt_usd
        db_type = "DEPOSIT"
        if "Dividend" in txn_type: db_type = "DIVIDEND"
        elif "Interest" in txn_type: db_type = "INTEREST"
        elif "Withdrawal" in txn_type: db_type = "WITHDRAWAL"
        log_transaction(user.id, f"{txn_type} (USD)", f_usd, db_type, rel_sym, txn_date, currency="USD")
        if txn_type in ["Deposit", "Withdrawal"] and amt_cad > 0:
            f_cad = -amt_cad if txn_type == "Withdrawal" else amt_cad
            log_transaction(user.id, f"{txn_type} (CAD Basis)", f_cad, db_type, rel_sym, txn_date, currency="CAD")
        st.success(f"Processed {txn_type}")


def pricing_page(user):
    st.header("📈 Update LEAP Prices (Yahoo Mid)")


    # Auto-refresh share/LEAP prices on page entry
    _auto_refresh_prices_on_enter(user, 'Update LEAP Prices', also_force_leap_mid=True)
    # Manual refresh button
    if st.button("🔄 Refresh Prices", key=f"refresh_prices_{page_name}_{user.id}", type="primary"):
        st.cache_data.clear()
        st.session_state[f"leap_mid_autorefresh_{user.id}"] = "__force__"
        st.rerun()

    assets, _ = get_portfolio_data(user.id)
    if assets.empty:
        st.info("No assets found.")
        return

    leaps = assets[assets['type'].str.contains("LONG|LEAP", case=False, na=False)].copy()
    if leaps.empty:
        st.info("No LEAP positions found.")
        return

    # Keep raw fields for pricing lookups
    leaps['ticker'] = leaps.get('ticker', leaps.get('symbol', ''))
    leaps['ticker_clean'] = leaps['ticker'].astype(str)
    leaps['exp_iso'] = leaps.get('expiration', '').apply(_iso_date)
    leaps['exp_disp'] = leaps['exp_iso'].apply(format_date_custom)

    # Determine option right from asset type
    def _right_from_type(t):
        s = str(t).upper()
        return "PUT" if "PUT" in s else "CALL"
    leaps['right'] = leaps['type'].apply(_right_from_type)

    leaps['sort_ticker'] = leaps['ticker_clean'].astype(str).str.upper()
    leaps.sort_values(by=['sort_ticker', 'exp_iso', 'strike_price'], inplace=True)

    leaps['type_disp'] = (
        leaps['type'].astype(str)
        .str.replace('LONG_', 'LEAP ', regex=False)
        .str.replace('LEAP_', 'LEAP ', regex=False)
        .str.title()
    )

    # Controls
    c1, c2, c3 = st.columns([1.4, 1.4, 2.2])
    with c1:
        auto_refresh = st.checkbox("Auto-refresh from Yahoo (once/day)", value=True)
    with c2:
        auto_save = st.checkbox("Auto-save refreshed prices to DB", value=True)
    with c3:
        st.caption("Uses Yahoo option chain **bid/ask mid** when available (fallback: lastPrice, bid, ask).")

    refresh_now = st.button("🔄 Refresh Yahoo Mid Prices", type="primary")

    # One-per-day guard
    today_key = f"leap_mid_autorefresh_{user.id}"
    today_iso = date.today().isoformat()

    def _refresh_and_optionally_save(df_in: pd.DataFrame, do_save: bool) -> pd.DataFrame:
        df = df_in.copy()
        mids = []
        changed = 0

        with st.spinner("Fetching Yahoo option mid prices..."):
            prog = st.progress(0)
            rows = list(df.itertuples(index=False))
            total = max(len(rows), 1)

            for i, r in enumerate(rows, start=1):
                sym = getattr(r, "ticker_clean", "")
                exp = getattr(r, "exp_iso", "")
                strike = getattr(r, "strike_price", None)
                right = getattr(r, "right", "CALL")

                mid = get_yahoo_option_mid_price(sym, exp, strike, right)
                mids.append(mid)

                prog.progress(i / total)

        df["yahoo_mid"] = mids

        # Choose new price: Yahoo mid if available else keep existing last_price
        df["current_db_price"] = df.get("last_price", 0.0).apply(clean_number)
        df["new_price"] = df.apply(
            lambda r: r["yahoo_mid"] if (r["yahoo_mid"] is not None and not pd.isna(r["yahoo_mid"])) else r["current_db_price"],
            axis=1
        ).astype(float)

        if do_save:
            for _, row in df.iterrows():
                new_p = float(row["new_price"])
                old_p = float(row["current_db_price"])
                if abs(new_p - old_p) > 1e-9:
                    supabase.table("assets").update({"last_price": new_p}).eq("id", row["id"]).execute()
                    changed += 1

            st.success(f"✅ Saved {changed} updated LEAP prices to the database.")
        return df

    should_refresh = refresh_now or (auto_refresh and st.session_state.get(today_key) != today_iso)

    if should_refresh:
        out_df = _refresh_and_optionally_save(leaps, auto_save)
        st.session_state[today_key] = today_iso
    else:
        # Show without hitting Yahoo
        out_df = leaps.copy()
        out_df["yahoo_mid"] = None
        out_df["current_db_price"] = out_df.get("last_price", 0.0).apply(clean_number)
        out_df["new_price"] = out_df["current_db_price"]

    # Display
    show = out_df[[
        "id", "ticker_clean", "exp_disp", "strike_price", "right", "type_disp",
        "current_db_price", "yahoo_mid", "new_price"
    ]].copy()

    show.rename(columns={
        "ticker_clean": "Ticker",
        "exp_disp": "Exp",
        "strike_price": "Strike",
        "right": "Right",
        "type_disp": "Type",
        "current_db_price": "DB Price",
        "yahoo_mid": "Yahoo Mid",
        "new_price": "Lead Price (New)"
    }, inplace=True)

    st.dataframe(
        show,
        hide_index=True,
        use_container_width=True,
        column_config={
            "id": None,
            "Strike": st.column_config.NumberColumn("Strike", format="$%.2f"),
            "DB Price": st.column_config.NumberColumn("DB Price", format="$%.4f"),
            "Yahoo Mid": st.column_config.NumberColumn("Yahoo Mid", format="$%.4f"),
            "Lead Price (New)": st.column_config.NumberColumn("Lead Price (New)", format="$%.4f"),
        }
    )

    st.caption("Tip: If a contract can't be found on Yahoo for that expiry/strike, the app keeps the stored DB price.")



def safe_reverse_ledger_transaction(transaction_id):
    res = supabase.table("transactions").select("*").eq("id", transaction_id).execute()
    if not res.data: return False, "Transaction not found."
    t = res.data[0]; user_id = t['user_id']
    if "TRADE" in t['type'] and "STOCK" in t['type']: 
        try:
            parts = t['description'].split(); action = parts[0]; qty = float(parts[1])
            assets = supabase.table("assets").select("*").eq("user_id", user_id).eq("ticker", t['related_symbol']).eq("type", "STOCK").execute()
            if assets.data:
                aid = assets.data[0]['id']; curr_q = assets.data[0]['quantity']
                new_q = curr_q - qty if action == "Buy" else curr_q + qty
                supabase.table("assets").update({"quantity": new_q}).eq("id", aid).execute()
        except: return False, "Auto-reverse failed."
    supabase.table("transactions").delete().eq("id", transaction_id).execute()
    return True, "Deleted."

def ledger_page(user):
    st.header("📜 Transaction Ledger")

    # --- Date Filtering ---
    c1, c2 = st.columns(2)
    with c1:
        start_date = st.date_input("From Date", value=(date.today() - timedelta(days=365)))
    with c2:
        end_date = st.date_input("To Date", value=date.today())

    # -------- Helpers --------
    _txg_re = re.compile(r"\bTXG:([A-Za-z0-9_\-]+)\b")
    _oid_re = re.compile(r"\bOID:([A-Za-z0-9_,\-]+)\b")

    def _to_date(v):
        if isinstance(v, datetime):
            return v.date()
        if isinstance(v, date):
            return v
        s = str(v or "").strip()
        if not s:
            return None
        s = s.split("T")[0].split(" ")[0]
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y"):
            try:
                return datetime.strptime(s, fmt).date()
            except Exception:
                pass
        return None

    def _extract_txg(desc: str):
        m = _txg_re.search(str(desc or ""))
        return m.group(1) if m else None

    def _extract_oids(desc: str):
        m = _oid_re.search(str(desc or ""))
        if not m:
            return []
        raw = m.group(1)
        return [x.strip() for x in raw.split(",") if x.strip()]

    def _friendly_action_group(gdf: pd.DataFrame) -> str:
        types = set([str(x).upper() for x in gdf.get("type", [])])
        descs = " ".join([str(x or "") for x in gdf.get("description", [])]).upper()

        if "ROLL" in descs:
            return "Roll"
        # Roll heuristic: OPTION_PREMIUM group with both Buy and Sell
        if any("OPTION_PREMIUM" in t for t in types):
            d = descs
            if (" BUY " in d or d.startswith("BUY")) and (" SELL " in d or d.startswith("SELL")):
                return "Roll"

        if "ASSIGN" in descs or "ASSIGNED" in descs:
            return "Assignment"
        if any("OPTION_EXPIRE" in t for t in types) and any(t.startswith("TRADE_STOCK") or t.startswith("TRADE_") for t in types):
            return "Assignment"

        if any("DEPOSIT" in t for t in types):
            return "Deposit"
        if any("WITHDRAWAL" in t for t in types):
            return "Withdrawal"
        if any("DIVIDEND" in t for t in types):
            return "Dividend"
        if any("INTEREST" in t for t in types):
            return "Interest"

        # single-row fallback
        if len(gdf) == 1:
            t0 = str(gdf.iloc[0].get("type", "")).upper()
            d0 = str(gdf.iloc[0].get("description", ""))
            if t0.startswith("TRADE_"):
                return "Trade"
            if "OPTION_PREMIUM" in t0:
                return "Option Trade"
            if "OPTION_EXPIRE" in t0:
                return "Expire Option"
            return d0.split(" ")[0] if d0 else "Transaction"

        return "Transaction"

    def _friendly_action_step(row: dict) -> str:
        t = str(row.get("type", "")).upper()
        d = str(row.get("description", "")).upper()
        if "OPTION_EXPIRE" in t or "EXPIRE" in d:
            return "Expire Option"
        if "OPTION_PREMIUM" in t:
            if d.startswith("BUY"):
                return "Buy to Close"
            if d.startswith("SELL"):
                return "Sell to Open"
            return "Option Premium"
        if t.startswith("TRADE_"):
            if d.startswith("BUY"):
                return "Buy Shares" if "STOCK" in t else "Buy Asset"
            if d.startswith("SELL"):
                return "Sell Shares" if "STOCK" in t else "Sell Asset"
            return "Asset Trade"
        return row.get("type") or "Step"

    def _reverse_transaction_row(row: dict):
        """Best-effort rollback of portfolio state for a transaction row."""
        tid = row.get("id")
        ttype = str(row.get("type", "")).upper()
        desc = str(row.get("description", ""))
        rel = str(row.get("related_symbol", "") or "").upper()

        # 1) Assignment expire: restore option statuses via OID list (most reliable)
        if "OPTION_EXPIRE" in ttype:
            oids = _extract_oids(desc)
            if oids:
                try:
                    supabase.table("options").update({"status": "open"}).in_("id", oids).execute()
                except Exception:
                    pass
            return

        # 2) Stock/LEAP trades: reverse asset quantity
        if ttype.startswith("TRADE_"):
            try:
                parts = desc.split()
                action = parts[0]
                qty = float(parts[1])
                ticker = rel or str(parts[2]).upper()

                asset_type = ttype.replace("TRADE_", "")
                q = supabase.table("assets").select("*").eq("user_id", row["user_id"]).eq("ticker", ticker)
                if "LEAP" in asset_type:
                    # try to parse expiration/strike from description
                    exp = None
                    strike = None
                    mexp = re.search(r"(\d{4}-[A-Za-z]{3}-\d{2})", desc)
                    if mexp:
                        exp = mexp.group(1)
                    mstr = re.search(r"\$(\d+(?:\.\d+)?)", desc)
                    if mstr:
                        strike = float(mstr.group(1))
                    q = q.like("type", "LEAP%")
                    if strike is not None:
                        q = q.eq("strike_price", strike)
                    if exp:
                        q = q.eq("expiration", exp)
                else:
                    q = q.eq("type", "STOCK")
                res = q.execute()
                if res.data:
                    aid = res.data[0]["id"]
                    curr = float(res.data[0].get("quantity") or 0)
                    new_q = curr - qty if action.upper() == "BUY" else curr + qty
                    supabase.table("assets").update({"quantity": new_q}).eq("id", aid).execute()
            except Exception:
                pass
            return

        # 3) Option premium: reverse open/close effect on options table
        if "OPTION_PREMIUM" in ttype:
            try:
                # desc: "Sell 2 NVDA 2026-Jan-16 $450 CALL ..."
                parts = desc.split()
                side = parts[0].upper()
                qty = int(float(parts[1]))
                ticker = str(parts[2]).upper()
                # parse exp
                exp = None
                mexp = re.search(r"(\d{4}-[A-Za-z]{3}-\d{2})", desc)
                if mexp:
                    exp = datetime.strptime(mexp.group(1), "%Y-%b-%d").date().isoformat()
                # parse strike
                mstr = re.search(r"\$(\d+(?:\.\d+)?)", desc)
                strike = float(mstr.group(1)) if mstr else None
                right = "CALL" if "CALL" in desc.upper() else ("PUT" if "PUT" in desc.upper() else None)

                if not (ticker and exp and strike is not None and right):
                    return

                if side == "SELL":
                    # Reverse an open: remove contracts from open options
                    res = supabase.table("options").select("*").eq("user_id", row["user_id"]).eq("symbol", ticker).eq("strike_price", strike).eq("expiration_date", exp).eq("type", right).eq("status", "open").order("open_date", desc=True).execute()
                    remaining = qty
                    if res.data:
                        for opt in res.data:
                            if remaining <= 0:
                                break
                            avail = int(opt.get("contracts") or opt.get("quantity") or 0)
                            if avail <= remaining:
                                supabase.table("options").update({"status": "closed"}).eq("id", opt["id"]).execute()
                                remaining -= avail
                            else:
                                supabase.table("options").update({"contracts": avail - remaining}).eq("id", opt["id"]).execute()
                                remaining = 0
                else:
                    # Reverse a close: reopen contracts as a new open option (best effort)
                    payload = {
                        "user_id": row["user_id"],
                        "ticker": ticker,
                        "symbol": ticker,
                        "strike_price": strike,
                        "expiration_date": exp,
                        "expiration": exp,
                        "open_date": str(row.get("transaction_date") or date.today().isoformat()),
                        "type": right,
                        "contracts": int(qty),
                        "premium_received": 0.0,
                        "status": "open",
                        "linked_asset_id": None
                    }
                    supabase.table("options").insert(payload).execute()
            except Exception:
                pass
            return

    def _delete_group(gdf: pd.DataFrame, group_label: str):
        # Roll back portfolio impact first (reverse chronological)
        for _, r in gdf.sort_values(["_d", "id_str"], ascending=[False, False]).iterrows():
            _reverse_transaction_row(r.to_dict())
            try:
                supabase.table("transactions").delete().eq("id", r["id"]).execute()
            except Exception:
                pass
        st.success(f"Deleted transaction ({group_label}) and rolled back portfolio changes.")
        st.cache_data.clear()
        st.rerun()

    # -------- Fetch + Group --------
    qb = supabase.table("transactions")\
        .select("*")\
        .eq("user_id", user.id)\
        .order("transaction_date", desc=False)

    rows = _fetch_all(qb)
    if not rows:
        st.info("No transactions yet.")
        return

    df = pd.DataFrame(rows)
    if df.empty:
        st.info("No transactions yet.")
        return

    df["_d"] = df["transaction_date"].apply(_to_date)
    df["id_str"] = df["id"].astype(str)
    df["txg"] = df["description"].apply(_extract_txg)
    df["gkey"] = df["txg"].fillna(df["id_str"])

    # sort
    df = df.sort_values(["_d", "id_str"], ascending=[True, True])

    # Build grouped list preserving order
    groups = []
    for gkey, gdf in df.groupby("gkey", sort=False):
        gdf = gdf.copy()
        gdate = gdf["_d"].dropna().min()
        # Choose a symbol safely (avoid pandas Series truth-value ambiguity)
        symbol = ""
        if "related_symbol" in gdf.columns:
            rs = gdf["related_symbol"].dropna()
            if not rs.empty:
                symbol = str(rs.iloc[0])
        if (not symbol) and "symbol" in gdf.columns:
            ss = gdf["symbol"].dropna()
            if not ss.empty:
                symbol = str(ss.iloc[0])
        action = _friendly_action_group(gdf)
        amount = float(pd.to_numeric(gdf.get("amount"), errors="coerce").fillna(0).sum())
        groups.append({"gkey": gkey, "date": gdate, "symbol": symbol, "action": action, "amount": amount, "gdf": gdf})

    # Running balance on groups (full history)
    running = 0.0
    for g in groups:
        running += float(g["amount"] or 0.0)
        g["running"] = running

    # Filter display groups by date range (inclusive)
    disp = [g for g in groups if (g["date"] is not None and start_date <= g["date"] <= end_date)]
    if not disp:
        st.info("No transactions in this date range.")
        return

    # --- Search / Filters ---
    f1, f2 = st.columns(2)
    sym_options = sorted({str(g.get("symbol") or "").upper() for g in disp if str(g.get("symbol") or "").strip()})
    act_options = sorted({str(g.get("action") or "") for g in disp if str(g.get("action") or "").strip()})

    with f1:
        sym_sel = st.multiselect("Filter Symbol", options=sym_options, default=[])
    with f2:
        act_sel = st.multiselect("Filter Action", options=act_options, default=[])

    if sym_sel:
        sym_set = {s.upper() for s in sym_sel}
        disp = [g for g in disp if str(g.get("symbol") or "").upper() in sym_set]
    if act_sel:
        act_set = set(act_sel)
        disp = [g for g in disp if str(g.get("action") or "") in act_set]

    # Sort newest first
    disp = sorted(disp, key=lambda g: (g.get("date") or date.min, str(g.get("gkey") or "")), reverse=True)

    # -------- Render --------
    hdr = st.columns([1.1, 1.0, 2.3, 1.2, 1.3, 0.8])
    hdr[0].markdown("**Date**")
    hdr[1].markdown("**Symbol**")
    hdr[2].markdown("**Action**")
    hdr[3].markdown("**Amount**")
    hdr[4].markdown("**Balance**")
    hdr[5].markdown("")

    for i, g in enumerate(disp):
        rowc = st.columns([1.1, 1.0, 2.3, 1.2, 1.3, 0.8])
        rowc[0].write(str(g["date"]))
        rowc[1].write(str(g["symbol"] or "").upper())
        rowc[2].write(g["action"])
        rowc[3].write(f"{g['amount']:,.2f}")
        rowc[4].write(f"{g['running']:,.2f}")

        if rowc[5].button("Delete", key=f"txg_del_{g['gkey']}_{i}"):
            _delete_group(g["gdf"], g["action"])

        with st.expander("Show details", expanded=False):
            sub = []
            for _, rr in g["gdf"].iterrows():
                sub.append({
                    "Date": str(rr.get("_d") or ""),
                    "Symbol": str(rr.get("related_symbol") or ""),
                    "Action": _friendly_action_step(rr.to_dict()),
                    "Amount": float(rr.get("amount") or 0.0),
                    "Details": str(rr.get("description") or "")
                })
            st.dataframe(pd.DataFrame(sub), use_container_width=True)

def trade_entry_page(user):
    st.header("⚡ Smart Trade Entry")

    # Helper: default option expiry is the next Friday from the selected trade date
    def _next_friday(d: date) -> date:
        days_ahead = (4 - d.weekday()) % 7
        if days_ahead == 0:
            days_ahead = 7
        return d + timedelta(days=days_ahead)

    # If a trade was just submitted, reset widgets so the page returns to the "landing" state
    if st.session_state.get("te_reset_pending"):
        for k in ["te_trade_date", "te_tick_sel", "te_man_sell", "te_man_buy", "te_exp_date", "te_pos_mode"]:
            if k in st.session_state:
                del st.session_state[k]
        del st.session_state["te_reset_pending"]

    if 'txn_success_msg' in st.session_state:
        st.success(st.session_state['txn_success_msg'])
        # Scroll back to the top so it feels like returning to the Enter Trade landing view
        st.markdown('<script>window.scrollTo(0,0);</script>', unsafe_allow_html=True)
        del st.session_state['txn_success_msg']
    trade_cat = st.radio("1. Type", ["Stock Trade", "Option Trade"], horizontal=True)
    c1, c2 = st.columns([1, 2])
    with c1: action = st.radio("2. Action", ["Buy", "Sell"], horizontal=True)
    with c2: trade_date = st.date_input("Trade Date", value=date.today(), key="te_trade_date")
    
    symbol = None
    if action == "Sell":
        holdings = get_distinct_holdings(user.id)
        opts = ["-- Select Asset --"] + holdings + ["Other"] if holdings else ["Other"]
        sel = st.selectbox("3. Ticker", opts, key="te_tick_sel")
        if sel == "Other": symbol = st.text_input("Ticker Symbol", key="te_man_sell").upper()
        elif sel != "-- Select Asset --": symbol = sel
    else: symbol = st.text_input("3. Ticker Symbol", key="te_man_buy").upper()

    if symbol:
        st.divider(); cur_p = get_live_stock_price(symbol)
        if cur_p > 0: st.metric(f"{symbol} Price", f"${cur_p:,.2f}"); def_p = float(cur_p)
        else: def_p = 0.0
        
        if trade_cat == "Stock Trade":
            c1, c2, c3 = st.columns(3)
            qty = c1.number_input("Shares Qty", min_value=1, step=1)
            price = c2.number_input("Price/Share", value=def_p, min_value=0.01)
            fees = c3.number_input("Total Fees", min_value=0.0, step=0.01, value=0.0)
            
            if st.button("Submit Stock Trade", type="primary"):
                update_asset_position(user.id, symbol, qty, price, action, trade_date, "STOCK", fees=fees)
                st.session_state['txn_success_msg'] = f"Recorded {action} {qty} {symbol} (Fees: ${fees})."; st.session_state['te_reset_pending'] = True; st.session_state['te_reset_pending'] = True; st.rerun()
        else:
            c1, c2, c3 = st.columns(3)
            exp_date = c1.date_input("Exp Date", value=_next_friday(trade_date), key="te_exp_date"); strike = c2.number_input("Strike", value=def_p, step=0.5); opt_type = c3.selectbox("Type", ["CALL", "PUT"])
            pos_mode = st.radio("Option Position", ["Short (Sell Premium)", "Long (LEAP / Bought Option)"], horizontal=True, key="te_pos_mode")
            linked_id = None; max_allowed = None
            if pos_mode.startswith("Short") and action == "Sell" and opt_type == "CALL":
                holdings_data = get_holdings_for_symbol(user.id, symbol); locked_map = get_locked_collateral(user.id)

                # If some open short calls were imported without a linked_asset_id, infer collateral already consumed
                total_open_calls = get_open_short_call_contracts(user.id, symbol)
                linked_total = sum(int(locked_map.get(str(h.get('id')), 0) or 0) for h in holdings_data)
                unlinked_calls = max(0, int(total_open_calls) - int(linked_total))

                # Allocate unlinked short calls to shares first, then LEAPs (conservative availability)
                stock_holdings = [h for h in holdings_data if "STOCK" in str(h.get('type','')).upper()]
                leap_holdings  = [h for h in holdings_data if ("LONG_" in str(h.get('type','')).upper()) or ("LEAP_" in str(h.get('type','')).upper())]
                unlinked_used = {}

                remaining = unlinked_calls
                for h in stock_holdings:
                    hid = str(h.get('id'))
                    qty = float(h.get('quantity', 0) or 0)
                    max_contracts = int(qty // 100)
                    take = min(remaining, max_contracts)
                    if take > 0:
                        unlinked_used[hid] = unlinked_used.get(hid, 0) + take
                        remaining -= take
                    if remaining <= 0:
                        break

                for h in leap_holdings:
                    if remaining <= 0:
                        break
                    hid = str(h.get('id'))
                    qty = int(float(h.get('quantity', 0) or 0))
                    take = min(remaining, qty)
                    if take > 0:
                        unlinked_used[hid] = unlinked_used.get(hid, 0) + take
                        remaining -= take

                valid_opts = {"None (Unsecured)": {"id": None, "limit": float('inf')}}; coll_found = False
                for h in holdings_data:
                    h_type = str(h.get('type', '')).upper()
                    h_qty = float(h.get('quantity', 0) or 0)
                    h_id = h.get('id')
                    linked_used = int(locked_map.get(str(h_id), 0) or 0)
                    inferred_used = int(unlinked_used.get(str(h_id), 0) or 0)
                    used_total = linked_used + inferred_used
                    if "STOCK" in h_type:
                        avail_shares = int(max(0, int(h_qty) - (used_total * 100)))
                        poss = int(avail_shares // 100)
                        if poss > 0:
                            coll_found = True
                            valid_opts[f"Shares: {avail_shares} avail"] = {"id": h_id, "limit": poss}
                    elif "LONG_" in h_type or "LEAP_" in h_type:
                        avail = int(max(0, int(h_qty) - used_total))
                        if avail > 0:
                            coll_found = True
                            valid_opts[f"LEAP ${float(h.get('strike_price',0)):.2f}: {avail} avail"] = {"id": h_id, "limit": avail}
                if coll_found:
                    sel_lbl = st.selectbox("Link Collateral", list(valid_opts.keys()))
                    linked_id = valid_opts[sel_lbl]["id"]; max_allowed = valid_opts[sel_lbl]["limit"]

            c4, c5, c6 = st.columns(3)
            qty = c4.number_input("Contracts", min_value=1, step=1)
            prem = c5.number_input("Premium", min_value=0.01)
            fees = c6.number_input("Total Fees", min_value=0.0, step=0.01, value=0.0)
            
            if st.button("Submit Option Trade", type="primary"):
                 if linked_id and max_allowed is not None and qty > max_allowed: st.error(f"Limit exceeded. Max: {max_allowed}"); return
                                  # Safety: ensure expiry comes from the Exp Date widget, not the trade date
                 if not isinstance(exp_date, date):
                     st.error('Expiry (Exp Date) is invalid. Please re-select the expiration date.'); return
                 
                 if pos_mode.startswith("Long"):
                     # Long option (LEAP) is an ASSET position tracked in the assets table
                     update_asset_position(user.id, symbol, qty, prem, action, trade_date, f"LEAP_{opt_type}", exp_date, strike, fees=fees)
                 else:
                     # Short option liability tracked in options table
                     update_short_option_position(user.id, symbol, qty, prem, action, trade_date, opt_type, exp_date, strike, fees=fees, linked_asset_id_override=linked_id)

                 mode_lbl = "LEAP" if pos_mode.startswith("Long") else "Short Option"
                 st.session_state['txn_success_msg'] = f"Recorded {action} {qty} {symbol} {mode_lbl} (Fees: ${fees})."; st.rerun()

def settings_page(user):
    st.header("⚙️ Settings")
    tab1, tab2 = st.tabs(["Assets", "Danger Zone"])
    with tab1:
        try:
            assets = supabase.table("assets").select("*").eq("user_id", user.id).execute().data
            if assets:
                a_map = {f"{a.get('ticker','UNK')} ({a['quantity']})": a['id'] for a in assets}
                sel_a = st.selectbox("Select Asset to Delete", list(a_map.keys()))
                if st.button("Delete Asset"): supabase.table("assets").delete().eq("id", a_map[sel_a]).execute(); st.rerun()
        except: pass
    with tab2:
        st.subheader("🔥 Reset Account")
        if "confirm_reset" not in st.session_state: st.session_state.confirm_reset = False
        if not st.session_state.confirm_reset:
            if st.button("Reset All Data"): st.session_state.confirm_reset = True; st.rerun()
        else:
            st.error("Are you sure? This is irreversible.")
            c1, c2 = st.columns(2)
            if c1.button("Yes, Delete Everything"):
                for t in ["options", "assets", "transactions", "portfolio_history"]: supabase.table(t).delete().eq("user_id", user.id).execute()
                st.session_state.confirm_reset = False; st.success("Account reset."); st.rerun()
            if c2.button("Cancel"): st.session_state.confirm_reset = False; st.rerun()

def main():
    # page config already set at top
    
    force_light_mode()  # <--- CALL THE NEW FUNCTION HERE
    
    if not handle_auth(): st.markdown("<br><h3 style='text-align:center;'>👈 Please log in.</h3>", unsafe_allow_html=True); return
    st.sidebar.divider()
    page = st.sidebar.radio("Menu", ["Dashboard", "Option Details", "Update LEAP Prices", "Weekly Snapshot", "Cash Management", "Enter Trade", "Ledger", "Import Data", "Settings"])
    
    # Track navigation changes (used for one-time auto refresh on page entry)
    prev_page = st.session_state.get("_current_page")
    if prev_page != page:
        st.session_state["_nav_seq"] = int(st.session_state.get("_nav_seq", 0)) + 1
        st.session_state["_current_page"] = page
user = st.session_state.user
    if page == "Dashboard": dashboard_page(user)
    elif page == "Option Details": option_details_page(user)
    elif page == "Update LEAP Prices": pricing_page(user)
    elif page == "Weekly Snapshot": snapshot_page(user)
    elif page == "Cash Management": cash_management_page(user)
    elif page == "Enter Trade": trade_entry_page(user)
    elif page == "Ledger": ledger_page(user)
    elif page == "Import Data": import_page(user)
    elif page == "Settings": settings_page(user)

if __name__ == "__main__":
    main()
