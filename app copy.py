import streamlit as st
import pandas as pd
import yfinance as yf
import re
from supabase import create_client, Client
from datetime import datetime, date, timedelta
import math

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
        </style>
    """, unsafe_allow_html=True)


# --------------------------------------------------------------------------------
# 0. CREDENTIALS
# --------------------------------------------------------------------------------
SUPABASE_URL = "https://iyiswgonnvknijrvsygb.supabase.co"
SUPABASE_KEY = "sb_publishable_FvqdkEPQaKuDUznTFIlApg_5EG5RYYN"

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
        if 'contracts' in df.columns:
            if 'quantity' not in df.columns: df['quantity'] = df['contracts']
            else: df['quantity'] = df['quantity'].fillna(df['contracts'])
        if 'quantity' in df.columns: df['quantity'] = df['quantity'].fillna(0)
    return df

def get_cash_balance(user_id):
    try:
        response = supabase.table("transactions").select("amount").eq("user_id", user_id).eq("currency", "USD").execute()
        df = pd.DataFrame(response.data)
        return df['amount'].sum() if not df.empty else 0.0
    except: return 0.0

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

def log_transaction(user_id, description, amount, trade_type, symbol, date_obj, currency="USD"):
    # 1. Force Amount to Float (prevents Numpy errors)
    try: safe_amount = float(amount)
    except: safe_amount = 0.0
    
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
        print(f"CRITICAL TRANSACTION ERROR: {e}")
        st.error(f"Failed to record transaction: {e}")

# --------------------------------------------------------------------------------
# 5. CORE LOGIC
# --------------------------------------------------------------------------------
def update_asset_position(user_id, symbol, quantity, price, action, date_obj, asset_type="STOCK", expiration=None, strike=None, fees=0.0):
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
    
    log_transaction(user_id, desc_label, cash_impact, "TRADE_" + asset_type, symbol, date_obj, currency="USD")
    
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

def update_short_option_position(user_id, symbol, quantity, price, action, date_obj, opt_type, expiration, strike, fees=0.0):
    premium = quantity * price * 100
    
    # Fee Logic:
    # Sell (Open): Receive Premium - Fees
    # Buy (Close): Pay Premium + Fees
    if action == "Sell":
        cash_impact = premium - fees
    else:
        cash_impact = -(premium + fees)
        
    formatted_exp = format_date_custom(expiration)
    desc = f"{action} {quantity} {symbol} {formatted_exp} ${strike} {opt_type}"
    if fees > 0: desc += f" (Fees: ${fees:.2f})"
    
    log_transaction(user_id, desc, cash_impact, "OPTION_PREMIUM", symbol, date_obj, currency="USD")
    
    if action == "Sell":
        linked_asset_id = None
        if opt_type == "CALL":
            stocks = supabase.table("assets").select("*").eq("user_id", user_id).eq("ticker", symbol).eq("type", "STOCK").neq("quantity", 0).execute()
            if stocks.data: linked_asset_id = stocks.data[0]['id']
            else:
                leaps = supabase.table("assets").select("*").eq("user_id", user_id).eq("ticker", symbol).neq("type", "STOCK").neq("quantity", 0).execute()
                if leaps.data: linked_asset_id = leaps.data[0]['id']
        payload = { 
            "user_id": user_id, "ticker": symbol, "symbol": symbol, "strike_price": strike, "expiration_date": str(expiration), "open_date": date_obj.isoformat(), "type": opt_type, 
            "contracts": int(quantity), "premium_received": price, "status": "open", "linked_asset_id": linked_asset_id
        }
        supabase.table("options").insert(payload).execute()
    else:
        res = supabase.table("options").select("*").eq("user_id", user_id).eq("symbol", symbol).eq("strike_price", strike).eq("expiration_date", str(expiration)).eq("type", opt_type).eq("status", "open").execute()
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
    try:
        res = supabase.table("options").select("linked_asset_id, contracts").eq("user_id", user_id).eq("status", "open").not_.is_("linked_asset_id", "null").execute()
        locked = {}
        for r in res.data: locked[r['linked_asset_id']] = locked.get(r['linked_asset_id'], 0) + r['contracts']
        return locked
    except: return {}
# --------------------------------------------------------------------------------
# 6. DASHBOARD & PAGES
# --------------------------------------------------------------------------------
def dashboard_page(user):
    st.header("📊 Executive Dashboard")
    
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
    
    # --- Calculations ---
    stock_value_usd = 0.0
    leap_value_usd = 0.0
    itm_liability_usd = 0.0
    
    # 1. Assets Calculation
    if not assets.empty:
        for idx, row in assets.iterrows():
            qty = clean_number(row['quantity'])
            r_type_raw = str(row.get('type', '')).upper().strip()
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
                leap_value_usd += (qty * 100 * manual_price)

    # 2. Options Liability Calculation & Aggregation
    grouped_options = {}
    
    if not options.empty:
        for idx, row in options.iterrows():
            qty = abs(clean_number(row.get('quantity') or row.get('contracts') or 0))
            strike = float(clean_number(row.get('strike_price') or row.get('strike') or 0))
            sym = str(row.get('symbol', '')).strip().upper()
            opt_type = str(row.get('type', '')).strip().upper()
            
            # Robust Expiration Parsing
            raw_exp = row.get('expiration')
            if raw_exp is None or pd.isna(raw_exp):
                raw_exp = row.get('expiration_date')
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
                            for item in sel_row['constituents']:
                                supabase.table("options").update({"status": "assigned"}).eq("id", item['id']).execute()
                            
                            trade_date = date.today()
                            total_shares = sel_row['qty'] * 100
                            
                            if sel_row['type'] == "PUT": 
                                update_asset_position(user.id, sel_row['symbol'], total_shares, sel_row['strike'], "Buy", trade_date, "STOCK")
                                st.success(f"Assigned on PUT. Bought {total_shares} shares.")
                                
                            elif sel_row['type'] == "CALL": 
                                update_asset_position(user.id, sel_row['symbol'], total_shares, sel_row['strike'], "Sell", trade_date, "STOCK")
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

                        # 3. ROLL (Using log_transaction to guarantee ledger update)
                        elif "Roll" in action_choice:
                            qty_safe = int(qty_to_process)
                            total_btc = float(btc_price) * qty_safe * 100
                            total_sto = float(new_premium) * qty_safe * 100
                            
                            # A. Inherit Linked Asset (Robust Fix)
                            inherited_link_id = None
                            if 'linked_assets' in sel_row and sel_row['linked_assets']:
                                inherited_link_id = sel_row['linked_assets'][0]
                            if not inherited_link_id:
                                for c in sel_row['constituents']:
                                    if c.get('linked_asset_id'):
                                        inherited_link_id = c['linked_asset_id']; break
                            
                            # B. Close Old Positions
                            remaining_to_close = qty_safe
                            for item in sel_row['constituents']:
                                if remaining_to_close <= 0: break
                                
                                row_qty = int(item['qty']); row_id = item['id']
                                old_open_date = item.get('open_date') or datetime.now().isoformat()
                                old_cost_basis = item.get('cost_basis') or 0.0
                                old_premium_rec = item.get('premium_received') or old_cost_basis
                                
                                if row_qty <= remaining_to_close:
                                    supabase.table("options").update({"status": "closed", "closing_price": float(btc_price), "closed_date": datetime.now().isoformat()}).eq("id", row_id).execute()
                                    remaining_to_close -= row_qty
                                else:
                                    keep_qty = row_qty - remaining_to_close
                                    supabase.table("options").update({"quantity": keep_qty, "contracts": keep_qty}).eq("id", row_id).execute()
                                    
                                    supabase.table("options").insert({
                                        "user_id": user.id, "symbol": sel_row['symbol'], "ticker": sel_row['symbol'], "type": sel_row['type'],
                                        "strike_price": sel_row['strike'], "expiration_date": sel_row['expiration'], "quantity": remaining_to_close, "contracts": remaining_to_close,
                                        "status": "closed", "cost_basis": old_cost_basis, "premium_received": old_premium_rec, "open_date": old_open_date,
                                        "closing_price": float(btc_price), "closed_date": datetime.now().isoformat()
                                    }).execute()
                                    remaining_to_close = 0

                            # C. Record Transactions (Using Central Log Function)
                            # This fixes the Ledger/Cash issue by enforcing correct date formats
                            txn_date_today = date.today()
                            
                            if total_btc > 0:
                                log_transaction(
                                    user.id,
                                    f"Roll BTC ({qty_safe}x): {sel_row['symbol']} {sel_row['type']} ${sel_row['strike']}",
                                    -total_btc, # Expense
                                    "OPTION_PREMIUM",
                                    sel_row['symbol'],
                                    txn_date_today
                                )
                            
                            if total_sto > 0:
                                log_transaction(
                                    user.id,
                                    f"Roll STO ({qty_safe}x): {sel_row['symbol']} {sel_row['type']} ${new_strike}",
                                    total_sto, # Income
                                    "OPTION_PREMIUM",
                                    sel_row['symbol'],
                                    txn_date_today
                                )
                            
                            # D. Open New Position (With Link ID)
                            supabase.table("options").insert({
                                "user_id": user.id, "symbol": sel_row['symbol'], "ticker": sel_row['symbol'], "type": sel_row['type'],
                                "strike_price": float(new_strike), "expiration_date": new_exp.isoformat(), 
                                "quantity": qty_safe, "contracts": qty_safe,
                                "status": "open", "cost_basis": float(new_premium), "premium_received": float(new_premium), 
                                "open_date": datetime.now().isoformat(),
                                "linked_asset_id": inherited_link_id 
                            }).execute()

                            st.success(f"Rolled {qty_safe} contracts. Net Cash: ${total_sto - total_btc:+,.2f}")
                            st.cache_data.clear() # Forces the ledger and cash header to refresh
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
            
            # Chart Logic
            if 'exchange_rate' in hist_df.columns:
                hist_df['Value (CAD)'] = hist_df['total_equity'] * hist_df['exchange_rate'].fillna(1.0)
            else:
                hist_df['Value (CAD)'] = hist_df['total_equity'] * get_usd_to_cad_rate()
            
            st.line_chart(hist_df.set_index('snapshot_date')[['Value (CAD)']])

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
                curr_year = curr_date.year
                
                # --- A. Net Deposits ---
                if i == 0:
                    prev_date = pd.Timestamp.min
                    prev_eq = 0.0
                else:
                    prev_row = hist_df.iloc[i-1]
                    prev_date = prev_row['snapshot_date']
                    prev_eq = float(prev_row['total_equity'])
                
                net_dep = 0.0
                if not tx_df.empty:
                    mask = (tx_df['transaction_date'] > prev_date) & (tx_df['transaction_date'] <= curr_date)
                    net_dep = tx_df.loc[mask, 'amount'].sum()
                
                # --- B. Profit/Loss Period ---
                if i == 0:
                    pl_dol = 0.0
                    pl_pct = 0.0
                else:
                    pl_dol = (curr_eq - net_dep) - prev_eq
                    pl_pct = (pl_dol / prev_eq) if prev_eq != 0 else 0.0

                # --- C. YTD Metrics ---
                prev_year_mask = hist_df['snapshot_date'].dt.year == (curr_year - 1)
                prev_year_df = hist_df[prev_year_mask]
                
                if not prev_year_df.empty:
                    base_row = prev_year_df.iloc[-1]
                    base_eq = float(base_row['total_equity'])
                    base_date = base_row['snapshot_date']
                else:
                    this_year_df = hist_df[hist_df['snapshot_date'].dt.year == curr_year]
                    base_row = this_year_df.iloc[0]
                    base_eq = float(base_row['total_equity'])
                    base_date = base_row['snapshot_date']
                
                if curr_date == base_date:
                    ytd_pct = 0.0
                    weekly_compound = 0.0
                else:
                    ytd_dep = 0.0
                    if not tx_df.empty:
                        ytd_mask = (tx_df['transaction_date'] > base_date) & (tx_df['transaction_date'] <= curr_date)
                        ytd_dep = tx_df.loc[ytd_mask, 'amount'].sum()
                    ytd_pl_dol = (curr_eq - ytd_dep) - base_eq
                    ytd_pct = (ytd_pl_dol / base_eq) if base_eq != 0 else 0.0
                    
                    # Weekly Compound Avg
                    days = (curr_date - base_date).days
                    weeks = days / 7.0
                    if weeks >= 1:
                        try:
                            weekly_compound = ((1 + ytd_pct) ** (1 / weeks)) - 1
                        except: weekly_compound = 0.0
                    else: weekly_compound = 0.0

                table_data.append({
                    "Date": curr_date.strftime('%Y-%m-%d'),
                    "Equity": curr_eq,
                    "Net Dep": net_dep,
                    "P/L $": pl_dol,
                    "P/L %": pl_pct,
                    "YTD %": ytd_pct,
                    "Wkly Avg %": weekly_compound
                })

            # 4. Display Logic
            final_df = pd.DataFrame(table_data).iloc[::-1]

            # --- CUSTOM PANDAS STYLING ---
            # This is the robust way to handle -$1,234.56 format while keeping right alignment
            def currency_fmt(x):
                if pd.isna(x): return "$0.00"
                return f"-${abs(x):,.2f}" if x < 0 else f"${x:,.2f}"

            def pct_fmt(x):
                return f"{x:.2f}%"

            # Apply formatting to specific columns
            # note: We use st.column_config to rename headers, but style to format values
            styled_df = final_df.style.format({
                "Equity": currency_fmt,
                "Net Dep": currency_fmt,
                "P/L $": currency_fmt,
                "P/L %": pct_fmt,
                "YTD %": pct_fmt,
                "Wkly Avg %": pct_fmt
            })

            st.dataframe(
                styled_df,
                column_config={
                    "Date": st.column_config.TextColumn("Snapshot Date"),
                    "Equity": st.column_config.Column("Total Equity (USD)"),
                    "Net Dep": st.column_config.Column("Net Deposits", help="Net Deposits/Withdrawals since last snapshot"),
                    "P/L $": st.column_config.Column("Profit/Loss $"),
                    "P/L %": st.column_config.Column("Profit/Loss %"),
                    "YTD %": st.column_config.Column("YTD %"),
                    "Wkly Avg %": st.column_config.Column("Wkly Avg %", help="Compounded Weekly Growth Rate (YTD)"),
                },
                hide_index=True,
                use_container_width=True
            )

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
                rename_map = {'quantity': 'qty', 'contracts': 'qty', 'symbol': 'ticker', 'stock': 'ticker', 'cost': 'price', 'premium': 'price', 'commission': 'fees', 'comm': 'fees', 'expiration_date': 'expiration', 'expiry': 'expiration', 'exp': 'expiration', 'strike_price': 'strike'}
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
                rename_map = {'quantity': 'qty', 'contracts': 'qty', 'symbol': 'ticker', 'stock': 'ticker', 'cost': 'price', 'premium': 'price', 'commission': 'fees', 'comm': 'fees', 'expiration_date': 'expiration', 'expiry': 'expiration', 'exp': 'expiration', 'strike_price': 'strike'}
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
                    'type': 'category', 'class': 'category', # Map 'Type' to Category
                    'option_type': 'opt_type', 'right': 'opt_type' # Call/Put
                }
                # Be careful not to overwrite 'type' if it refers to Call/Put vs Asset Class
                # Heuristic: If 'category' column exists, use it. If not, look for 'class'.
                df.rename(columns=rename_map, inplace=True)
                
                # 2. Date Parsing & Sorting (CRITICAL STEP)
                df['date_parsed'] = pd.to_datetime(df['date'], errors='coerce')
                df.sort_values(by='date_parsed', ascending=True, inplace=True)
                
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
                        
                        sym = str(r.get('ticker','')).upper().replace("NONE","").strip()
                        qty = abs(clean_number(r.get('qty', 0)))
                        
                        # Price cleaning
                        try: raw_p = str(r.get('price', 0)).replace('$','').replace(',','').strip(); price = abs(float(raw_p)) 
                        except: price = 0.0
                        
                        fees = get_fees(r)
                        act = clean_action_input(r.get('action', 'Buy'))
                        
                        # Specific Fields
                        opt_type = str(r.get('opt_type', 'CALL')).strip().upper() # Call/Put
                        strike = abs(clean_number(r.get('strike', 0)))
                        exp = r.get('expiration')
                        
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
    st.header("📈 Update LEAP Prices")
    assets, _ = get_portfolio_data(user.id)
    if not assets.empty:
        leaps = assets[assets['type'].str.contains("LONG|LEAP", case=False, na=False)].copy()
        if not leaps.empty:
            leaps['ticker'] = leaps.get('ticker', leaps['symbol'])
            leaps['sort_ticker'] = leaps['ticker'].astype(str).str.upper()
            leaps.sort_values(by=['sort_ticker', 'expiration', 'strike_price'], inplace=True)
            leaps['type_disp'] = leaps['type'].str.replace('LONG_', 'LEAP ').replace('LEAP_', 'LEAP ').str.title()
            leaps['expiration'] = leaps['expiration'].apply(format_date_custom)
            
            edited_df = st.data_editor(leaps[['id', 'ticker', 'expiration', 'strike_price', 'type_disp', 'last_price']], column_config={"id": None, "ticker": "Ticker", "expiration": "Exp", "strike_price": st.column_config.NumberColumn("Strike", format="$%.2f"), "last_price": st.column_config.NumberColumn("Price (USD)", format="$%.2f", required=True)}, hide_index=True, key="leap_editor", use_container_width=True)
            
            if st.button("Save Updated Prices", type="primary"):
                for _, row in edited_df.iterrows(): supabase.table("assets").update({"last_price": row['last_price']}).eq("id", row['id']).execute()
                st.success("Prices updated."); st.rerun()
        else: st.info("No LEAP positions found.")
    else: st.info("No assets found.")

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
    with c1: start_date = st.date_input("From Date", value=(date.today() - timedelta(days=365)))
    with c2: end_date = st.date_input("To Date", value=date.today())

    try:
        # 1. Fetch ALL data sorted by Date Ascending (Oldest First)
        # We need full history to calculate the Running Balance correctly
        res = supabase.table("transactions")\
            .select("*")\
            .eq("user_id", user.id)\
            .order("transaction_date", desc=False)\
            .limit(10000)\
            .execute()
            
        df = pd.DataFrame(res.data)
        
        if not df.empty:
            # 2. Calculate Running Balance
            df['running_balance'] = df['amount'].cumsum()

            # 3. Helper: Clean Symbol (3-4 digits)
            def get_clean_symbol(s):
                if not s or s == "None": return ""
                s = str(s).upper()
                if "CASH" in s: return "USD"
                # Handle "NVIDIA (NVDA)" or "XNYS:NVDA"
                if "(" in s: return s.split("(")[1].replace(")", "")
                if ":" in s: return s.split(":")[-1]
                return s[:5].strip() 

            # 4. Helper: Clean Action (Short & concise)
            def get_clean_action(row):
                desc = str(row.get('description', '')).title()
                type_ = str(row.get('type', '')).upper()
                
                # Priority Keywords
                if "Roll" in desc: return "Roll"
                if "Assign" in desc: return "Assign"
                if "Expire" in desc: return "Expire"
                if "Dividend" in desc or "DIVIDEND" in type_: return "Dividend"
                if "Interest" in desc: return "Interest"
                if "Deposit" in desc: return "Deposit"
                if "Withdraw" in desc: return "Withdraw"
                
                # Fallback: First word of description (usually "Buy", "Sell")
                return desc.split(' ')[0]

            df['display_symbol'] = df['related_symbol'].apply(get_clean_symbol)
            df['display_action'] = df.apply(get_clean_action, axis=1)

            # 5. ROBUST DATE FILTERING
            # Convert string dates (which might contain timestamps) to Date Objects
            df['dt_temp'] = pd.to_datetime(df['transaction_date'])
            
            # Filter based on Date Only (ignores time component)
            mask = (df['dt_temp'].dt.date >= start_date) & (df['dt_temp'].dt.date <= end_date)
            display_df = df[mask].copy()

            # 6. Sort Descending for Display (Newest on Top)
            display_df = display_df.sort_values(by='transaction_date', ascending=False)
            
            st.caption(f"Showing {len(display_df)} transactions.")

            # --- TABLE HEADER ---
            h_date, h_sym, h_act, h_amt, h_bal, h_del = st.columns([2, 1.5, 1.5, 2, 2, 1])
            h_date.markdown("**Date**")
            h_sym.markdown("**Symbol**")
            h_act.markdown("**Action**")
            h_amt.markdown("**Amount**")
            h_bal.markdown("**Balance**")
            h_del.markdown("**Del**")
            st.divider()
            
            # --- TABLE ROWS ---
            for index, row in display_df.iterrows():
                c_date, c_sym, c_act, c_amt, c_bal, c_del = st.columns([2, 1.5, 1.5, 2, 2, 1])
                
                # Date
                c_date.write(format_date_custom(row['transaction_date']))
                
                # Symbol
                c_sym.write(row['display_symbol'])
                
                # Action
                c_act.write(row['display_action'])
                
                # Amount
                amt = row['amount']
                color = "green" if amt >= 0 else "red"
                c_amt.markdown(f":{color}[${amt:,.2f}]")
                
                # Balance
                bal = row['running_balance']
                c_bal.markdown(f"**${bal:,.2f}**")
                
                # Delete
                if st.session_state.delete_confirm_id == row['id']:
                    if c_del.button("Confirm", key=f"confirm_{row['id']}", type="primary"):
                        safe_reverse_ledger_transaction(row['id'])
                        st.session_state.delete_confirm_id = None
                        st.cache_data.clear()
                        st.rerun()
                else:
                    if c_del.button("✖", key=f"trash_{row['id']}"):
                        st.session_state.delete_confirm_id = row['id']
                        st.rerun()

        else: st.info("No transactions found in history.")
    except Exception as e: st.error(f"Error loading ledger: {e}")

def trade_entry_page(user):
    st.header("⚡ Smart Trade Entry")
    if 'txn_success_msg' in st.session_state: st.success(st.session_state['txn_success_msg']); del st.session_state['txn_success_msg']
    trade_cat = st.radio("1. Type", ["Stock Trade", "Option Trade"], horizontal=True)
    c1, c2 = st.columns([1, 2])
    with c1: action = st.radio("2. Action", ["Buy", "Sell"], horizontal=True)
    with c2: trade_date = st.date_input("Trade Date", value=date.today())
    
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
                st.session_state['txn_success_msg'] = f"Recorded {action} {qty} {symbol} (Fees: ${fees})."; st.rerun()
        else:
            c1, c2, c3 = st.columns(3)
            exp_date = c1.date_input("Exp Date"); strike = c2.number_input("Strike", value=def_p, step=0.5); opt_type = c3.selectbox("Type", ["CALL", "PUT"])
            linked_id = None; max_allowed = None
            if action == "Sell" and opt_type == "CALL":
                holdings_data = get_holdings_for_symbol(user.id, symbol); locked_map = get_locked_collateral(user.id)
                valid_opts = {"None (Unsecured)": {"id": None, "limit": float('inf')}}; coll_found = False
                for h in holdings_data:
                    h_type = h.get('type', ''); h_qty = h.get('quantity', 0); h_id = h['id']; used = locked_map.get(h_id, 0)
                    if "STOCK" in h_type: 
                        avail = h_qty - (used * 100); poss = int(avail // 100)
                        if poss > 0: coll_found = True; valid_opts[f"Shares: {int(avail)} avail"] = {"id": h_id, "limit": poss}
                    elif "LONG_" in h_type or "LEAP_" in h_type: 
                        avail = int(h_qty - used)
                        if avail > 0: coll_found = True; valid_opts[f"LEAP ${float(h.get('strike_price',0)):.2f}: {avail} avail"] = {"id": h_id, "limit": avail}
                if coll_found:
                    sel_lbl = st.selectbox("Link Collateral", list(valid_opts.keys()))
                    linked_id = valid_opts[sel_lbl]["id"]; max_allowed = valid_opts[sel_lbl]["limit"]

            c4, c5, c6 = st.columns(3)
            qty = c4.number_input("Contracts", min_value=1, step=1)
            prem = c5.number_input("Premium", min_value=0.01)
            fees = c6.number_input("Total Fees", min_value=0.0, step=0.01, value=0.0)
            
            if st.button("Submit Option Trade", type="primary"):
                 if linked_id and max_allowed is not None and qty > max_allowed: st.error(f"Limit exceeded. Max: {max_allowed}"); return
                 update_short_option_position(user.id, symbol, qty, prem, action, trade_date, opt_type, exp_date, strike, fees=fees)
                 st.session_state['txn_success_msg'] = f"Recorded {action} {qty} {symbol} Option (Fees: ${fees})."; st.rerun()

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
    st.set_page_config(page_title="Asset Dashboard", layout="wide")
    
    force_light_mode()  # <--- CALL THE NEW FUNCTION HERE
    
    if not handle_auth(): st.markdown("<br><h3 style='text-align:center;'>👈 Please log in.</h3>", unsafe_allow_html=True); return
    st.sidebar.divider()
    page = st.sidebar.radio("Menu", ["Dashboard", "Update LEAP Prices", "Weekly Snapshot", "Cash Management", "Enter Trade", "Ledger", "Import Data", "Settings"])
    user = st.session_state.user
    if page == "Dashboard": dashboard_page(user)
    elif page == "Update LEAP Prices": pricing_page(user)
    elif page == "Weekly Snapshot": snapshot_page(user)
    elif page == "Cash Management": cash_management_page(user)
    elif page == "Enter Trade": trade_entry_page(user)
    elif page == "Ledger": ledger_page(user)
    elif page == "Import Data": import_page(user)
    elif page == "Settings": settings_page(user)

if __name__ == "__main__":
    main()
