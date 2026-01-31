 (cd "$(git rev-parse --show-toplevel)" && git apply --3way <<'EOF' 
diff --git a/app.py b/app.py
index 5ce629881bb6c92556916404602207b84b0ec91a..51def825cbe57c3e228e42f306f7cf0f62f093b5 100644
--- a/app.py
+++ b/app.py
@@ -3392,363 +3392,877 @@ def _fetch_long_leaps(user, symbol: str | None = None):
     if symbol:
         q = q.eq("symbol", symbol) if "symbol" in (symbol or "") else q.eq("ticker", symbol)
     try:
         res = q.execute()
         rows = res.data or []
     except Exception:
         rows = []
     out = []
     for r in rows:
         t = str(r.get("type") or "").upper()
         if ("LEAP_" in t) or ("LEAPS_" in t) or ("LONG_" in t):
             if float(r.get("quantity") or 0) > 0:
                 out.append(r)
     return out
 
 
 def _fetch_stock_tickers(user):
     try:
         res = supabase.table("assets").select("ticker").eq("user_id", user.id).eq("type", "STOCK").neq("quantity", 0).execute()
         if res.data:
             return sorted(list({str(r.get("ticker") or "").upper() for r in res.data if str(r.get("ticker") or "")}))
         return []
     except Exception:
         return []
 
+def _build_short_position_list(user, leap_only: bool = False):
+    rows = _fetch_open_shorts(user)
+    positions = {}
+    cutoff = date.today() + timedelta(days=180)
+    for r in rows:
+        sym = str(r.get("symbol") or r.get("ticker") or "").upper()
+        exp = _iso_date(r.get("expiration_date") or r.get("expiration"))
+        strike = clean_number(r.get("strike_price") or r.get("strike") or 0)
+        opt_type = str(r.get("type") or "").upper()
+        qty = int(r.get("contracts") or r.get("quantity") or 0)
+        if not sym or not exp or qty <= 0:
+            continue
+        if leap_only:
+            try:
+                exp_date = date.fromisoformat(exp)
+            except Exception:
+                continue
+            if exp_date < cutoff:
+                continue
+        key = (sym, exp, strike, opt_type)
+        positions[key] = positions.get(key, 0) + qty
+    return [
+        {"symbol": k[0], "exp": k[1], "strike": k[2], "type": k[3], "qty": v}
+        for k, v in positions.items()
+    ]
+
+
+def _build_long_option_list(user):
+    rows = _fetch_long_leaps(user)
+    positions = {}
+    for r in rows:
+        sym = str(r.get("symbol") or r.get("ticker") or "").upper()
+        exp = _iso_date(r.get("expiration") or r.get("expiration_date"))
+        strike = clean_number(r.get("strike_price") or r.get("strike") or 0)
+        qty = int(r.get("quantity") or 0)
+        opt_type = "PUT" if "PUT" in str(r.get("type") or "").upper() else "CALL"
+        if not sym or not exp or qty <= 0:
+            continue
+        key = (sym, exp, strike, opt_type)
+        positions[key] = positions.get(key, 0) + qty
+    return [
+        {"symbol": k[0], "exp": k[1], "strike": k[2], "type": k[3], "qty": v}
+        for k, v in positions.items()
+    ]
+
+
+def _option_label_map(positions):
+    label_map = {}
+    for p in positions:
+        exp = _iso_date(p.get("exp"))
+        strike = float(p.get("strike") or 0)
+        opt_type = str(p.get("type") or "").upper()
+        sym = str(p.get("symbol") or "").upper()
+        qty = int(p.get("qty") or 0)
+        if not sym or not exp:
+            continue
+        label = f"{sym} {exp} ${strike:g} {opt_type} (Avail: {qty})"
+        label_map[label] = {
+            "symbol": sym,
+            "exp": exp,
+            "strike": strike,
+            "type": opt_type,
+            "qty": qty,
+        }
+    return label_map
+
+
+def _positions_by_symbol(positions):
+    by_symbol = {}
+    for p in positions:
+        sym = str(p.get("symbol") or "").upper()
+        if not sym:
+            continue
+        by_symbol.setdefault(sym, []).append(p)
+    for sym in by_symbol:
+        by_symbol[sym] = sorted(by_symbol[sym], key=lambda x: (x.get("exp") or "", x.get("strike") or 0))
+    return by_symbol
+
+
+def _parse_option_label(label, label_map):
+    if label in label_map:
+        return label_map[label]
+    match = re.match(
+        r"^(?P<symbol>\S+)\s+(?P<exp>\d{4}-\d{2}-\d{2})\s+\$(?P<strike>[\d.]+)\s+(?P<type>CALL|PUT)",
+        str(label).strip().upper(),
+    )
+    if match:
+        return {
+            "symbol": match.group("symbol"),
+            "exp": match.group("exp"),
+            "strike": float(match.group("strike")),
+            "type": match.group("type"),
+            "qty": 0,
+        }
+    return {"symbol": str(label).strip().upper(), "exp": "", "strike": 0.0, "type": "", "qty": 0}
+
+
+def _bulk_option_cash_change(action: str, contracts: float, premium: float, fees: float, btc_price: float = 0.0, new_premium: float = 0.0) -> float:
+    fees = float(fees or 0)
+    contracts = float(contracts or 0)
+    premium = float(premium or 0)
+    if action == "Roll":
+        gross = (float(new_premium or 0) - float(btc_price or 0)) * contracts * 100.0
+        return gross - fees
+    if action in ["Expire", "Assign"]:
+        return -fees
+    gross = premium * contracts * 100.0
+    if action in ["Buy to Close"]:
+        return -(gross + fees)
+    return gross - fees
+
+
+def _resolve_position_for_symbol(symbol: str, by_symbol):
+    sym = str(symbol or "").upper()
+    if not sym:
+        return None
+    positions = by_symbol.get(sym, [])
+    return positions[0] if positions else None
+
+
+def _bulk_expire_contracts(user, symbol, exp, strike, opt_type, contracts):
+    open_rows = [
+        o for o in _fetch_open_shorts(user, symbol)
+        if _iso_date(o.get("expiration_date") or o.get("expiration")) == exp
+        and float(o.get("strike_price") or 0) == float(strike or 0)
+        and str(o.get("type") or "").upper() == str(opt_type or "").upper()
+    ]
+    open_rows = sorted(open_rows, key=lambda x: (str(x.get("expiration_date") or ""), int(x.get("id") or 0)))
+    remaining = int(contracts or 0)
+    for o in open_rows:
+        if remaining <= 0:
+            break
+        qty = int(o.get("contracts") or o.get("quantity") or 0)
+        if qty <= 0:
+            continue
+        if qty <= remaining:
+            _bulk_expire_option(int(o["id"]))
+            remaining -= qty
+        else:
+            supabase.table("options").update({"contracts": qty - remaining}).eq("id", o["id"]).execute()
+            clone = dict(o)
+            clone.pop("id", None)
+            clone["contracts"] = remaining
+            clone["status"] = "expired"
+            clone["closing_price"] = 0.0
+            clone["closed_date"] = datetime.now().isoformat()
+            supabase.table("options").insert(clone).execute()
+            remaining = 0
+
+
+def _bulk_assign_contracts(user, symbol, exp, strike, opt_type, contracts):
+    open_rows = [
+        o for o in _fetch_open_shorts(user, symbol)
+        if _iso_date(o.get("expiration_date") or o.get("expiration")) == exp
+        and float(o.get("strike_price") or 0) == float(strike or 0)
+        and str(o.get("type") or "").upper() == str(opt_type or "").upper()
+    ]
+    open_rows = sorted(open_rows, key=lambda x: (str(x.get("expiration_date") or ""), int(x.get("id") or 0)))
+    remaining = int(contracts or 0)
+    for o in open_rows:
+        if remaining <= 0:
+            break
+        qty = int(o.get("contracts") or 0)
+        if qty <= 0:
+            continue
+        take = min(remaining, qty)
+        handle_assignment(user.id, o["id"], symbol, float(o.get("strike_price") or 0), str(o.get("type") or "").upper(), take)
+        remaining -= take
+
 def _bulk_expire_option(option_id: int):
     try:
         supabase.table("options").update({
             "status": "expired",
             "closing_price": 0.0,
             "closed_date": datetime.now().isoformat()
         }).eq("id", option_id).execute()
         return True
     except Exception:
         return False
 
 
 def bulk_entries_page(user):
 
     try:
         st.header("🧾 Bulk Entries")
         st.caption("Enter multiple transactions at once. Review the summary, then submit all updates in one batch.")
 
         asset_kind = st.selectbox("Asset", ["Stock", "LEAP", "Shorts"], key="bulk_asset_kind")
 
         # shared defaults
         today = datetime.now().date()
         nf = _next_friday(today)
+        leap_default_exp = _third_friday_next_december(today)
+
+        short_positions_all = _build_short_position_list(user)
+        short_positions_leap = _build_short_position_list(user, leap_only=True)
+        long_positions = _build_long_option_list(user)
+
+        short_label_map = _option_label_map(short_positions_all)
+        short_leap_label_map = _option_label_map(short_positions_leap)
+        long_label_map = _option_label_map(long_positions)
+
+        short_by_symbol = _positions_by_symbol(short_positions_all)
+        short_leap_by_symbol = _positions_by_symbol(short_positions_leap)
+        long_by_symbol = _positions_by_symbol(long_positions)
+
+        summary_rows = []
+        process_rows = []
+        process_kind = asset_kind
 
         if asset_kind == "Stock":
             action = st.selectbox("Action", ["Buy", "Sell"], key="bulk_stock_action")
-            # Ticker choices: for Sell, limit to tickers you own
             owned = _fetch_stock_tickers(user)
 
             default_rows = st.session_state.get("bulk_rows_stock", [])
             if not default_rows:
                 default_rows = [{
                     "Date": today,
                     "Ticker": "",
                     "Qty": 100,
                     "Price": 0.0,
                     "Fees": 0.0,
                     "Net Cash Change": 0.0,
                 }]
 
             col_cfg = {
                 "Date": st.column_config.DateColumn("Date", default=today),
                 "Ticker": st.column_config.SelectboxColumn("Ticker", options=owned, required=False) if action == "Sell" and owned else st.column_config.TextColumn("Ticker"),
                 "Qty": st.column_config.NumberColumn("Qty", step=1, default=100),
                 "Price": st.column_config.NumberColumn("Price", step=0.01),
                 "Fees": st.column_config.NumberColumn("Fees", step=0.01, default=0.0),
                 "Net Cash Change": st.column_config.NumberColumn("Net Cash Change", disabled=True),
             }
 
             df = st.data_editor(default_rows, num_rows="dynamic", key="bulk_stock_editor", column_config=col_cfg)
-            # compute net cash
-            rows = []
+            st.session_state["bulk_rows_stock"] = df
+
             for r in df:
                 qty = float(r.get("Qty") or 0)
                 price = float(r.get("Price") or 0)
                 fees = float(r.get("Fees") or 0)
-                r["Net Cash Change"] = _bulk_net_cash_change("Stock", action, qty, price, fees)
-                r["Action"] = action
-                rows.append(r)
-            st.session_state["bulk_rows_stock"] = rows
-
-            summary = rows
-            process_kind = "Stock"
+                sym = str(r.get("Ticker") or "").upper().strip()
+                if price <= 0 and sym:
+                    price = float(get_live_stock_price(sym) or 0)
+                net_cash = _bulk_net_cash_change("Stock", action, qty, price, fees)
+                r["Net Cash Change"] = net_cash
+                r["Price"] = price
+                summary_rows.append({**r, "Ticker": sym, "Action": action, "Price": price, "Net Cash Change": net_cash})
+                process_rows.append({**r, "Ticker": sym, "Action": action, "Price": price})
 
         elif asset_kind == "LEAP":
             action = st.selectbox(
                 "Action",
                 ["Buy to Close", "Sell to Open", "Sell to Close", "Roll", "Expire", "Assign"],
                 key="bulk_leap_action"
             )
-            # For LEAP bulk we treat them as LONG options in assets table (not shorts)
-            # We'll provide ticker dropdown for actions that use existing positions.
-            longs = _fetch_long_leaps(user)
-            long_syms = sorted({str(r.get("symbol") or r.get("ticker") or "").upper() for r in longs if str(r.get("symbol") or r.get("ticker") or "")})
-            default_rows = st.session_state.get("bulk_rows_leap", [])
-            if not default_rows:
-                default_rows = [{
-                    "Date": today,
-                    "Ticker": "",
-                    "Exp": _third_friday_next_december(today),
-                    "Strike": 0.0,
-                    "Type": "CALL",
-                    "Contracts": 1,
-                    "Premium": 0.0,
-                    "Fees": 0.0,
-                    "Net Cash Change": 0.0,
-                }]
 
-            if action in ["Sell to Close", "Roll", "Expire", "Assign", "Buy to Close"]:
-                ticker_col = st.column_config.SelectboxColumn("Ticker", options=long_syms, required=False) if long_syms else st.column_config.TextColumn("Ticker")
-            else:
-                ticker_col = st.column_config.TextColumn("Ticker")
+            ticker_options = []
+            if action in ["Buy to Close", "Roll", "Expire", "Assign"]:
+                ticker_options = list(short_leap_label_map.keys())
+            elif action == "Sell to Close":
+                ticker_options = list(long_label_map.keys())
 
-            col_cfg = {
-                "Date": st.column_config.DateColumn("Date", default=today),
-                "Ticker": ticker_col,
-                "Exp": st.column_config.DateColumn("Exp", default=_third_friday_next_december(today)),
-                "Strike": st.column_config.NumberColumn("Strike", step=0.5),
-                "Type": st.column_config.SelectboxColumn("Type", options=["CALL", "PUT"]),
-                "Contracts": st.column_config.NumberColumn("Contracts", step=1, default=1),
-                "Premium": st.column_config.NumberColumn("Premium", step=0.01),
-                "Fees": st.column_config.NumberColumn("Fees", step=0.01, default=0.0),
-                "Net Cash Change": st.column_config.NumberColumn("Net Cash Change", disabled=True),
-            }
+            default_rows = st.session_state.get(f"bulk_rows_leap_{action}", [])
+            if not default_rows:
+                default_ticker = ticker_options[0] if ticker_options else ""
+                base = {"Date": today, "Ticker": default_ticker, "Fees": 0.0, "Net Cash Change": 0.0}
+                if action == "Sell to Open":
+                    base.update({
+                        "Strike Date": leap_default_exp,
+                        "Strike Price": 0.0,
+                        "Type": "CALL",
+                        "Contracts": 1,
+                        "Premium": 0.0,
+                    })
+                elif action == "Roll":
+                    base.update({
+                        "Contracts to Roll": 1,
+                        "BTC Price": 0.0,
+                        "New Strike": 0.0,
+                        "New Premium": 0.0,
+                        "New Strike Date": nf,
+                    })
+                elif action in ["Expire", "Assign"]:
+                    base.update({"Contracts to " + action: 1})
+                else:
+                    base.update({"Contracts": 1, "Premium": 0.0})
+                default_rows = [base]
 
-            # For Roll, we need extra cols
-            if action == "Roll":
-                for k,v in {
+            col_cfg = {"Date": st.column_config.DateColumn("Date", default=today)}
+            if ticker_options:
+                col_cfg["Ticker"] = st.column_config.SelectboxColumn("Ticker", options=ticker_options, required=False)
+            else:
+                col_cfg["Ticker"] = st.column_config.TextColumn("Ticker")
+
+            if action == "Sell to Open":
+                col_cfg.update({
+                    "Strike Date": st.column_config.DateColumn("Strike Date", default=leap_default_exp),
+                    "Strike Price": st.column_config.NumberColumn("Strike Price", step=0.5),
+                    "Type": st.column_config.SelectboxColumn("Type", options=["CALL", "PUT"]),
+                    "Contracts": st.column_config.NumberColumn("Contracts", step=1, default=1),
+                    "Premium": st.column_config.NumberColumn("Premium", step=0.01),
+                    "Fees": st.column_config.NumberColumn("Fees", step=0.01, default=0.0),
+                })
+            elif action == "Roll":
+                col_cfg.update({
+                    "Contracts to Roll": st.column_config.NumberColumn("Contracts to Roll", step=1, default=1),
                     "BTC Price": st.column_config.NumberColumn("BTC Price", step=0.01),
                     "New Strike": st.column_config.NumberColumn("New Strike", step=0.5),
                     "New Premium": st.column_config.NumberColumn("New Premium", step=0.01),
-                    "New Exp": st.column_config.DateColumn("New Exp", default=nf),
-                }.items():
-                    col_cfg[k]=v
+                    "New Strike Date": st.column_config.DateColumn("New Strike Date", default=nf),
+                    "Fees": st.column_config.NumberColumn("Fees", step=0.01, default=0.0),
+                })
+            elif action in ["Expire", "Assign"]:
+                col_cfg.update({
+                    "Contracts to " + action: st.column_config.NumberColumn(f"Contracts to {action}", step=1, default=1),
+                    "Fees": st.column_config.NumberColumn("Fees", step=0.01, default=0.0),
+                })
+            else:
+                col_cfg.update({
+                    "Contracts": st.column_config.NumberColumn("Contracts", step=1, default=1),
+                    "Premium": st.column_config.NumberColumn("Premium", step=0.01),
+                    "Fees": st.column_config.NumberColumn("Fees", step=0.01, default=0.0),
+                })
 
+            col_cfg["Net Cash Change"] = st.column_config.NumberColumn("Net Cash Change", disabled=True)
             df = st.data_editor(default_rows, num_rows="dynamic", key="bulk_leap_editor", column_config=col_cfg)
-            rows=[]
+            st.session_state[f"bulk_rows_leap_{action}"] = df
+
             for r in df:
-                c = float(r.get("Contracts") or 0)
-                prem = float(r.get("Premium") or 0)
                 fees = float(r.get("Fees") or 0)
-                # LEAP cash change uses option premium
-                r["Net Cash Change"] = _bulk_net_cash_change("LEAP", "Sell" if "Sell" in action else "Buy", c, prem, fees)
-                r["Action"] = action
-                rows.append(r)
-            st.session_state["bulk_rows_leap"] = rows
-            summary = rows
-            process_kind = "LEAP"
+                label = r.get("Ticker") or ""
+                if action == "Sell to Open":
+                    sym = str(label).upper().strip()
+                    exp = r.get("Strike Date") or leap_default_exp
+                    exp_iso = _iso_date(exp)
+                    strike = float(r.get("Strike Price") or 0)
+                    opt_type = str(r.get("Type") or "CALL").upper()
+                    contracts = float(r.get("Contracts") or 0)
+                    premium = float(r.get("Premium") or 0)
+                    if premium <= 0 and sym and exp_iso and strike:
+                        premium = float(get_yahoo_option_mid_price(sym, exp_iso, strike, opt_type) or 0)
+                    net_cash = _bulk_option_cash_change(action, contracts, premium, fees)
+                    r["Premium"] = premium
+                elif action == "Roll":
+                    pos = _parse_option_label(label, short_leap_label_map)
+                    sym = pos["symbol"]
+                    exp_iso = pos["exp"] or ""
+                    strike = float(pos.get("strike") or 0)
+                    opt_type = pos.get("type") or "CALL"
+                    contracts = float(r.get("Contracts to Roll") or 0)
+                    btc_price = float(r.get("BTC Price") or 0)
+                    new_strike = float(r.get("New Strike") or 0)
+                    new_exp = _iso_date(r.get("New Strike Date") or nf)
+                    new_premium = float(r.get("New Premium") or 0)
+                    if btc_price <= 0 and sym and exp_iso and strike:
+                        btc_price = float(get_yahoo_option_mid_price(sym, exp_iso, strike, opt_type) or 0)
+                    if new_premium <= 0 and sym and new_exp and new_strike:
+                        new_premium = float(get_yahoo_option_mid_price(sym, new_exp, new_strike, opt_type) or 0)
+                    net_cash = _bulk_option_cash_change(action, contracts, 0, fees, btc_price=btc_price, new_premium=new_premium)
+                    premium = 0.0
+                    r["BTC Price"] = btc_price
+                    r["New Premium"] = new_premium
+                elif action in ["Expire", "Assign"]:
+                    pos = _parse_option_label(label, short_leap_label_map)
+                    sym = pos["symbol"]
+                    exp_iso = pos["exp"]
+                    strike = float(pos.get("strike") or 0)
+                    opt_type = pos.get("type") or "CALL"
+                    contracts = float(r.get(f"Contracts to {action}") or 0)
+                    premium = 0.0
+                    net_cash = _bulk_option_cash_change(action, contracts, premium, fees)
+                elif action == "Buy to Close":
+                    pos = _parse_option_label(label, short_leap_label_map)
+                    sym = pos["symbol"]
+                    exp_iso = pos["exp"]
+                    strike = float(pos.get("strike") or 0)
+                    opt_type = pos.get("type") or "CALL"
+                    contracts = float(r.get("Contracts") or 0)
+                    premium = float(r.get("Premium") or 0)
+                    if premium <= 0 and sym and exp_iso and strike:
+                        premium = float(get_yahoo_option_mid_price(sym, exp_iso, strike, opt_type) or 0)
+                    net_cash = _bulk_option_cash_change(action, contracts, premium, fees)
+                    r["Premium"] = premium
+                else:
+                    pos = _parse_option_label(label, long_label_map)
+                    sym = pos["symbol"]
+                    exp_iso = pos["exp"]
+                    strike = float(pos.get("strike") or 0)
+                    opt_type = pos.get("type") or "CALL"
+                    contracts = float(r.get("Contracts") or 0)
+                    premium = float(r.get("Premium") or 0)
+                    if premium <= 0 and sym and exp_iso and strike:
+                        premium = float(get_yahoo_option_mid_price(sym, exp_iso, strike, opt_type) or 0)
+                    net_cash = _bulk_option_cash_change(action, contracts, premium, fees)
+                    r["Premium"] = premium
+
+                r["Net Cash Change"] = net_cash
+
+                summary_rows.append({
+                    **r,
+                    "Ticker": sym,
+                    "Action": action,
+                    "Premium": premium if action != "Roll" else r.get("New Premium", 0.0),
+                    "Net Cash Change": net_cash,
+                })
+                process_rows.append({
+                    **r,
+                    "_symbol": sym,
+                    "_exp": exp_iso,
+                    "_strike": strike,
+                    "_type": opt_type,
+                    "_action": action,
+                    "_btc": r.get("BTC Price", 0.0),
+                    "_new_strike": r.get("New Strike", 0.0),
+                    "_new_exp": _iso_date(r.get("New Strike Date") or nf),
+                    "_new_premium": r.get("New Premium", 0.0),
+                    "_premium": premium,
+                })
 
         else:  # Shorts
             action = st.selectbox(
                 "Action",
-                ["Buy to Close", "Sell to Open", "Roll", "Expire", "Assign"],
+                ["Buy to Close", "Sell to Open", "Sell to Close", "Roll", "Expire", "Assign"],
                 key="bulk_short_action"
             )
-            open_shorts = _fetch_open_shorts(user)
-            short_syms = sorted({str(r.get("symbol") or "").upper() for r in open_shorts if str(r.get("symbol") or "")})
-            default_rows = st.session_state.get("bulk_rows_short", [])
-            if not default_rows:
-                default_rows = [{
-                    "Date": today,
-                    "Ticker": "",
-                    "Exp": nf,
-                    "Strike": 0.0,
-                    "Type": "CALL",
-                    "Contracts": 1,
-                    "Premium": 0.0,
-                    "Fees": 0.0,
-                    "Net Cash Change": 0.0,
-                }]
 
-            # ticker column based on action
+            ticker_options = []
             if action in ["Buy to Close", "Roll", "Expire", "Assign"]:
-                ticker_col = st.column_config.SelectboxColumn("Ticker", options=short_syms, required=False) if short_syms else st.column_config.TextColumn("Ticker")
-            else:
-                # Sell to open: limit to tickers with holdings
-                tick_opts = get_distinct_holdings(user.id)
-                ticker_col = st.column_config.SelectboxColumn("Ticker", options=tick_opts, required=False) if tick_opts else st.column_config.TextColumn("Ticker")
+                ticker_options = list(short_label_map.keys())
+            elif action == "Sell to Close":
+                ticker_options = list(long_label_map.keys())
+            elif action == "Sell to Open":
+                ticker_options = get_distinct_holdings(user.id)
 
-            col_cfg = {
-                "Date": st.column_config.DateColumn("Date", default=today),
-                "Ticker": ticker_col,
-                "Exp": st.column_config.DateColumn("Exp", default=nf),
-                "Strike": st.column_config.NumberColumn("Strike", step=0.5),
-                "Type": st.column_config.SelectboxColumn("Type", options=["CALL", "PUT"]),
-                "Contracts": st.column_config.NumberColumn("Contracts", step=1, default=1),
-                "Premium": st.column_config.NumberColumn("Premium", step=0.01),
-                "Fees": st.column_config.NumberColumn("Fees", step=0.01, default=0.0),
-                "Net Cash Change": st.column_config.NumberColumn("Net Cash Change", disabled=True),
-            }
-            if action == "Roll":
-                for k,v in {
+            default_rows = st.session_state.get(f"bulk_rows_short_{action}", [])
+            if not default_rows:
+                default_ticker = ticker_options[0] if ticker_options else ""
+                base = {"Date": today, "Ticker": default_ticker, "Fees": 0.0, "Net Cash Change": 0.0}
+                if action == "Sell to Open":
+                    base.update({
+                        "Strike Date": nf,
+                        "Strike Price": 0.0,
+                        "Type": "CALL",
+                        "Contracts": 1,
+                        "Premium": 0.0,
+                    })
+                elif action == "Roll":
+                    base.update({
+                        "Contracts to Roll": 1,
+                        "BTC Price": 0.0,
+                        "New Strike": 0.0,
+                        "New Premium": 0.0,
+                        "New Strike Date": nf,
+                    })
+                elif action in ["Expire", "Assign"]:
+                    base.update({"Contracts to " + action: 1})
+                else:
+                    base.update({"Contracts": 1, "Premium": 0.0})
+                default_rows = [base]
+
+            col_cfg = {"Date": st.column_config.DateColumn("Date", default=today)}
+            if ticker_options:
+                col_cfg["Ticker"] = st.column_config.SelectboxColumn("Ticker", options=ticker_options, required=False)
+            else:
+                col_cfg["Ticker"] = st.column_config.TextColumn("Ticker")
+
+            if action == "Sell to Open":
+                col_cfg.update({
+                    "Strike Date": st.column_config.DateColumn("Strike Date", default=nf),
+                    "Strike Price": st.column_config.NumberColumn("Strike Price", step=0.5),
+                    "Type": st.column_config.SelectboxColumn("Type", options=["CALL", "PUT"]),
+                    "Contracts": st.column_config.NumberColumn("Contracts", step=1, default=1),
+                    "Premium": st.column_config.NumberColumn("Premium", step=0.01),
+                    "Fees": st.column_config.NumberColumn("Fees", step=0.01, default=0.0),
+                })
+            elif action == "Roll":
+                col_cfg.update({
+                    "Contracts to Roll": st.column_config.NumberColumn("Contracts to Roll", step=1, default=1),
                     "BTC Price": st.column_config.NumberColumn("BTC Price", step=0.01),
                     "New Strike": st.column_config.NumberColumn("New Strike", step=0.5),
                     "New Premium": st.column_config.NumberColumn("New Premium", step=0.01),
-                    "New Exp": st.column_config.DateColumn("New Exp", default=nf),
-                }.items():
-                    col_cfg[k]=v
+                    "New Strike Date": st.column_config.DateColumn("New Strike Date", default=nf),
+                    "Fees": st.column_config.NumberColumn("Fees", step=0.01, default=0.0),
+                })
+            elif action in ["Expire", "Assign"]:
+                col_cfg.update({
+                    "Contracts to " + action: st.column_config.NumberColumn(f"Contracts to {action}", step=1, default=1),
+                    "Fees": st.column_config.NumberColumn("Fees", step=0.01, default=0.0),
+                })
+            else:
+                col_cfg.update({
+                    "Contracts": st.column_config.NumberColumn("Contracts", step=1, default=1),
+                    "Premium": st.column_config.NumberColumn("Premium", step=0.01),
+                    "Fees": st.column_config.NumberColumn("Fees", step=0.01, default=0.0),
+                })
 
+            col_cfg["Net Cash Change"] = st.column_config.NumberColumn("Net Cash Change", disabled=True)
             df = st.data_editor(default_rows, num_rows="dynamic", key="bulk_short_editor", column_config=col_cfg)
-            rows=[]
+            st.session_state[f"bulk_rows_short_{action}"] = df
+
             for r in df:
-                c=float(r.get("Contracts") or 0)
-                prem=float(r.get("Premium") or 0)
-                fees=float(r.get("Fees") or 0)
-                # shorts: sell to open positive, buy to close negative
-                act_cash = "Sell" if action == "Sell to Open" else ("Buy" if action == "Buy to Close" else "Buy")
-                r["Net Cash Change"] = _bulk_net_cash_change("Shorts", act_cash, c, prem, fees)
-                r["Action"]=action
-                rows.append(r)
-            st.session_state["bulk_rows_short"]=rows
-            summary=rows
-            process_kind="Shorts"
+                fees = float(r.get("Fees") or 0)
+                label = r.get("Ticker") or ""
+                if action == "Sell to Open":
+                    sym = str(label).upper().strip()
+                    exp_iso = _iso_date(r.get("Strike Date") or nf)
+                    strike = float(r.get("Strike Price") or 0)
+                    opt_type = str(r.get("Type") or "CALL").upper()
+                    contracts = float(r.get("Contracts") or 0)
+                    premium = float(r.get("Premium") or 0)
+                    if premium <= 0 and sym and exp_iso and strike:
+                        premium = float(get_yahoo_option_mid_price(sym, exp_iso, strike, opt_type) or 0)
+                    net_cash = _bulk_option_cash_change(action, contracts, premium, fees)
+                    r["Premium"] = premium
+                elif action == "Roll":
+                    pos = _parse_option_label(label, short_label_map)
+                    sym = pos["symbol"]
+                    exp_iso = pos["exp"] or ""
+                    strike = float(pos.get("strike") or 0)
+                    opt_type = pos.get("type") or "CALL"
+                    contracts = float(r.get("Contracts to Roll") or 0)
+                    btc_price = float(r.get("BTC Price") or 0)
+                    new_strike = float(r.get("New Strike") or 0)
+                    new_exp = _iso_date(r.get("New Strike Date") or nf)
+                    new_premium = float(r.get("New Premium") or 0)
+                    if btc_price <= 0 and sym and exp_iso and strike:
+                        btc_price = float(get_yahoo_option_mid_price(sym, exp_iso, strike, opt_type) or 0)
+                    if new_premium <= 0 and sym and new_exp and new_strike:
+                        new_premium = float(get_yahoo_option_mid_price(sym, new_exp, new_strike, opt_type) or 0)
+                    net_cash = _bulk_option_cash_change(action, contracts, 0, fees, btc_price=btc_price, new_premium=new_premium)
+                    premium = 0.0
+                    r["BTC Price"] = btc_price
+                    r["New Premium"] = new_premium
+                elif action in ["Expire", "Assign"]:
+                    pos = _parse_option_label(label, short_label_map)
+                    sym = pos["symbol"]
+                    exp_iso = pos["exp"]
+                    strike = float(pos.get("strike") or 0)
+                    opt_type = pos.get("type") or "CALL"
+                    contracts = float(r.get(f"Contracts to {action}") or 0)
+                    premium = 0.0
+                    net_cash = _bulk_option_cash_change(action, contracts, premium, fees)
+                elif action == "Sell to Close":
+                    pos = _parse_option_label(label, long_label_map)
+                    sym = pos["symbol"]
+                    exp_iso = pos["exp"]
+                    strike = float(pos.get("strike") or 0)
+                    opt_type = pos.get("type") or "CALL"
+                    contracts = float(r.get("Contracts") or 0)
+                    premium = float(r.get("Premium") or 0)
+                    if premium <= 0 and sym and exp_iso and strike:
+                        premium = float(get_yahoo_option_mid_price(sym, exp_iso, strike, opt_type) or 0)
+                    net_cash = _bulk_option_cash_change(action, contracts, premium, fees)
+                    r["Premium"] = premium
+                else:
+                    pos = _parse_option_label(label, short_label_map)
+                    sym = pos["symbol"]
+                    exp_iso = pos["exp"]
+                    strike = float(pos.get("strike") or 0)
+                    opt_type = pos.get("type") or "CALL"
+                    contracts = float(r.get("Contracts") or 0)
+                    premium = float(r.get("Premium") or 0)
+                    if premium <= 0 and sym and exp_iso and strike:
+                        premium = float(get_yahoo_option_mid_price(sym, exp_iso, strike, opt_type) or 0)
+                    net_cash = _bulk_option_cash_change(action, contracts, premium, fees)
+                    r["Premium"] = premium
+
+                r["Net Cash Change"] = net_cash
+
+                summary_rows.append({
+                    **r,
+                    "Ticker": sym,
+                    "Action": action,
+                    "Premium": premium if action != "Roll" else r.get("New Premium", 0.0),
+                    "Net Cash Change": net_cash,
+                })
+                process_rows.append({
+                    **r,
+                    "_symbol": sym,
+                    "_exp": exp_iso,
+                    "_strike": strike,
+                    "_type": opt_type,
+                    "_action": action,
+                    "_btc": r.get("BTC Price", 0.0),
+                    "_new_strike": r.get("New Strike", 0.0),
+                    "_new_exp": _iso_date(r.get("New Strike Date") or nf),
+                    "_new_premium": r.get("New Premium", 0.0),
+                    "_premium": premium,
+                })
 
         st.divider()
         st.subheader("Review & Submit")
-        if not summary:
+        if not summary_rows:
             st.info("Add at least one row above.")
             return
 
-        # Show summary table
         try:
             import pandas as pd
-            sdf = pd.DataFrame(summary)
+            sdf = pd.DataFrame(summary_rows)
             st.dataframe(sdf, use_container_width=True)
             total_cash = float(sdf.get("Net Cash Change", pd.Series([0])).sum())
             st.metric("Total Net Cash Change", f"${total_cash:,.2f}")
         except Exception:
             total_cash = 0.0
 
-        if st.checkbox("I confirm these transactions are correct", key="bulk_confirm"):
-            if st.button("✅ Submit All Transactions", type="primary"):
-                errors=[]
-                ok=0
-                for r in summary:
-                    try:
-                        d = r.get("Date") or today
-                        if isinstance(d, str):
-                            d = date.fromisoformat(d[:10])
-                        sym = str(r.get("Ticker") or "").upper().strip()
-                        fees = float(r.get("Fees") or 0)
-                        if process_kind == "Stock":
-                            qty=float(r.get("Qty") or 0)
-                            price=float(r.get("Price") or 0)
-                            update_asset_position(user.id, sym, qty, price, r.get("Action"), d, "STOCK", fees=fees)
-                            ok += 1
-                        elif process_kind == "LEAP":
-                            act = r.get("Action")
-                            contracts=int(float(r.get("Contracts") or 0))
-                            prem=float(r.get("Premium") or 0)
-                            opt_type=str(r.get("Type") or "CALL").upper()
-                            exp = r.get("Exp") or _third_friday_next_december(today)
-                            if isinstance(exp, str):
-                                exp = date.fromisoformat(exp[:10])
-                            strike=float(r.get("Strike") or 0)
-                            if act == "Sell to Open":
-                                update_asset_position(user.id, sym, contracts, prem, "Buy", d, f"LEAP_{opt_type}", exp, strike, fees=fees)  # treat as opening long
-                                ok += 1
-                            elif act == "Sell to Close":
-                                update_asset_position(user.id, sym, contracts, prem, "Sell", d, f"LEAP_{opt_type}", exp, strike, fees=fees)
-                                ok += 1
-                            elif act == "Expire":
-                                # just reduce quantity to 0 at $0
-                                update_asset_position(user.id, sym, contracts, 0.0, "Sell", d, f"LEAP_{opt_type}", exp, strike, fees=fees)
-                                ok += 1
-                            else:
-                                # Roll/Assign/Buy to Close not fully supported for LEAP longs in this MVP
-                                errors.append(f"LEAP action not supported yet in bulk: {act} ({sym})")
-                        else:
-                            act = r.get("Action")
-                            contracts=int(float(r.get("Contracts") or 0))
-                            prem=float(r.get("Premium") or 0)
-                            opt_type=str(r.get("Type") or "CALL").upper()
-                            exp = r.get("Exp") or nf
-                            if isinstance(exp, str):
-                                exp = date.fromisoformat(exp[:10])
-                            strike=float(r.get("Strike") or 0)
-                            if act == "Sell to Open":
-                                update_short_option_position(user.id, sym, contracts, prem, "Sell", d, opt_type, exp, strike, fees=fees, linked_asset_id_override=None)
-                                ok += 1
-                            elif act == "Buy to Close":
-                                update_short_option_position(user.id, sym, contracts, prem, "Buy", d, opt_type, exp, strike, fees=fees, linked_asset_id_override=None)
-                                ok += 1
-                            elif act == "Expire":
-                                # find matching open options and expire contracts in order
-                                open_rows = [o for o in _fetch_open_shorts(user, sym) if str(o.get("type","")).upper()==opt_type and float(o.get("strike_price") or 0)==strike]
-                                # sort by expiration then id
-                                open_rows = sorted(open_rows, key=lambda x: (str(x.get("expiration_date") or ""), int(x.get("id") or 0)))
-                                remaining=contracts
-                                for o in open_rows:
-                                    if remaining<=0: break
-                                    qty=int(o.get("contracts") or o.get("quantity") or 0)
-                                    if qty<=0: continue
-                                    if qty<=remaining:
-                                        _bulk_expire_option(int(o["id"]))
-                                        remaining-=qty
-                                    else:
-                                        # split row by reducing contracts and creating expired row
-                                        supabase.table("options").update({"contracts": qty-remaining}).eq("id", o["id"]).execute()
-                                        # clone row with remaining contracts expired
-                                        clone = dict(o)
-                                        clone.pop("id", None)
-                                        clone["contracts"]=remaining
-                                        clone["status"]="expired"
-                                        clone["closing_price"]=0.0
-                                        clone["closed_date"]=datetime.now().isoformat()
-                                        supabase.table("options").insert(clone).execute()
-                                        remaining=0
-                                ok += 1
-                            elif act == "Assign":
-                                # Assign first matching open option rows
-                                open_rows = [o for o in _fetch_open_shorts(user, sym)]
-                                open_rows = sorted(open_rows, key=lambda x: (str(x.get("expiration_date") or ""), int(x.get("id") or 0)))
-                                remaining=contracts
-                                for o in open_rows:
-                                    if remaining<=0: break
-                                    qty=int(o.get("contracts") or 0)
-                                    if qty<=0: continue
-                                    take=min(remaining, qty)
-                                    handle_assignment(user.id, o["id"], sym, float(o.get("strike_price") or 0), str(o.get("type") or "").upper(), take)
-                                    remaining-=take
-                                ok += 1
-                            else:
-                                errors.append(f"Short action not supported yet in bulk: {act} ({sym})")
-                    except Exception as e:
-                        errors.append(f"{r.get('Ticker','')}: {e}")
-
-                if errors:
-                    st.error("Some rows failed:")
-                    for e in errors[:20]:
-                        st.write("•", e)
-                st.success(f"Submitted {ok} transactions.")
-                st.rerun()
+        if st.button("Open Confirmation Window", type="secondary"):
+            st.session_state["bulk_review_open"] = True
+
+        if st.session_state.get("bulk_review_open"):
+            with st.expander("Confirmation Window", expanded=True):
+                st.write("Please review the summary below. Confirming will submit all rows to the ledger and portfolio.")
+                st.dataframe(pd.DataFrame(summary_rows), use_container_width=True)
+                st.metric("Total Net Cash Change", f"${total_cash:,.2f}")
+                c1, c2 = st.columns(2)
+                with c1:
+                    if st.button("Confirm & Submit", type="primary"):
+                        errors = []
+                        ok = 0
+                        for r in process_rows:
+                            try:
+                                d = r.get("Date") or today
+                                if isinstance(d, str):
+                                    d = date.fromisoformat(d[:10])
+                                sym = str(r.get("_symbol") or r.get("Ticker") or "").upper().strip()
+                                fees = float(r.get("Fees") or 0)
+                                action = r.get("_action")
+
+                                if process_kind == "Stock":
+                                    qty = float(r.get("Qty") or 0)
+                                    price = float(r.get("Price") or 0)
+                                    update_asset_position(user.id, sym, qty, price, action, d, "STOCK", fees=fees)
+                                    ok += 1
+
+                                elif process_kind == "LEAP":
+                                    if action == "Sell to Open":
+                                        contracts = int(float(r.get("Contracts") or 0))
+                                        premium = float(r.get("_premium") or 0)
+                                        exp = r.get("Strike Date") or leap_default_exp
+                                        exp = date.fromisoformat(_iso_date(exp))
+                                        strike = float(r.get("Strike Price") or 0)
+                                        opt_type = str(r.get("Type") or "CALL").upper()
+                                        update_short_option_position(user.id, sym, contracts, premium, "Sell", d, opt_type, exp, strike, fees=fees)
+                                        ok += 1
+                                    elif action == "Buy to Close":
+                                        exp = r.get("_exp")
+                                        strike = float(r.get("_strike") or 0)
+                                        opt_type = str(r.get("_type") or "CALL").upper()
+                                        if not exp:
+                                            fallback = _resolve_position_for_symbol(sym, short_leap_by_symbol)
+                                            if fallback:
+                                                exp = fallback.get("exp")
+                                                strike = float(fallback.get("strike") or 0)
+                                                opt_type = fallback.get("type") or opt_type
+                                        if not exp:
+                                            raise ValueError("Missing expiration for Buy to Close.")
+                                        contracts = int(float(r.get("Contracts") or 0))
+                                        premium = float(r.get("_premium") or 0)
+                                        update_short_option_position(user.id, sym, contracts, premium, "Buy", d, opt_type, exp, strike, fees=fees)
+                                        ok += 1
+                                    elif action == "Sell to Close":
+                                        exp = r.get("_exp")
+                                        strike = float(r.get("_strike") or 0)
+                                        opt_type = str(r.get("_type") or "CALL").upper()
+                                        if not exp:
+                                            fallback = _resolve_position_for_symbol(sym, long_by_symbol)
+                                            if fallback:
+                                                exp = fallback.get("exp")
+                                                strike = float(fallback.get("strike") or 0)
+                                                opt_type = fallback.get("type") or opt_type
+                                        if not exp:
+                                            raise ValueError("Missing expiration for Sell to Close.")
+                                        contracts = int(float(r.get("Contracts") or 0))
+                                        premium = float(r.get("_premium") or 0)
+                                        update_asset_position(user.id, sym, contracts, premium, "Sell", d, f"LEAP_{opt_type}", exp, strike, fees=fees)
+                                        ok += 1
+                                    elif action == "Roll":
+                                        exp = r.get("_exp")
+                                        strike = float(r.get("_strike") or 0)
+                                        opt_type = str(r.get("_type") or "CALL").upper()
+                                        if not exp:
+                                            fallback = _resolve_position_for_symbol(sym, short_leap_by_symbol)
+                                            if fallback:
+                                                exp = fallback.get("exp")
+                                                strike = float(fallback.get("strike") or 0)
+                                                opt_type = fallback.get("type") or opt_type
+                                        if not exp:
+                                            raise ValueError("Missing expiration for Roll.")
+                                        contracts = int(float(r.get("Contracts to Roll") or 0))
+                                        btc_price = float(r.get("_btc") or 0)
+                                        new_premium = float(r.get("_new_premium") or 0)
+                                        new_strike = float(r.get("_new_strike") or 0)
+                                        new_exp = r.get("_new_exp") or nf
+                                        txg = uuid.uuid4().hex[:12]
+                                        update_short_option_position(user.id, sym, contracts, btc_price, "Buy", d, opt_type, exp, strike, fees=fees, txg=txg)
+                                        update_short_option_position(user.id, sym, contracts, new_premium, "Sell", d, opt_type, new_exp, new_strike, fees=0.0, txg=txg)
+                                        ok += 1
+                                    elif action == "Expire":
+                                        exp = r.get("_exp")
+                                        strike = float(r.get("_strike") or 0)
+                                        opt_type = str(r.get("_type") or "CALL").upper()
+                                        if not exp:
+                                            fallback = _resolve_position_for_symbol(sym, short_leap_by_symbol)
+                                            if fallback:
+                                                exp = fallback.get("exp")
+                                                strike = float(fallback.get("strike") or 0)
+                                                opt_type = fallback.get("type") or opt_type
+                                        contracts = int(float(r.get("Contracts to Expire") or 0))
+                                        _bulk_expire_contracts(user, sym, exp, strike, opt_type, contracts)
+                                        ok += 1
+                                    elif action == "Assign":
+                                        exp = r.get("_exp")
+                                        strike = float(r.get("_strike") or 0)
+                                        opt_type = str(r.get("_type") or "CALL").upper()
+                                        if not exp:
+                                            fallback = _resolve_position_for_symbol(sym, short_leap_by_symbol)
+                                            if fallback:
+                                                exp = fallback.get("exp")
+                                                strike = float(fallback.get("strike") or 0)
+                                                opt_type = fallback.get("type") or opt_type
+                                        contracts = int(float(r.get("Contracts to Assign") or 0))
+                                        _bulk_assign_contracts(user, sym, exp, strike, opt_type, contracts)
+                                        ok += 1
+
+                                else:  # Shorts
+                                    if action == "Sell to Open":
+                                        contracts = int(float(r.get("Contracts") or 0))
+                                        premium = float(r.get("_premium") or 0)
+                                        exp = r.get("Strike Date") or nf
+                                        exp = date.fromisoformat(_iso_date(exp))
+                                        strike = float(r.get("Strike Price") or 0)
+                                        opt_type = str(r.get("Type") or "CALL").upper()
+                                        update_short_option_position(user.id, sym, contracts, premium, "Sell", d, opt_type, exp, strike, fees=fees)
+                                        ok += 1
+                                    elif action == "Buy to Close":
+                                        exp = r.get("_exp")
+                                        strike = float(r.get("_strike") or 0)
+                                        opt_type = str(r.get("_type") or "CALL").upper()
+                                        if not exp:
+                                            fallback = _resolve_position_for_symbol(sym, short_by_symbol)
+                                            if fallback:
+                                                exp = fallback.get("exp")
+                                                strike = float(fallback.get("strike") or 0)
+                                                opt_type = fallback.get("type") or opt_type
+                                        if not exp:
+                                            raise ValueError("Missing expiration for Buy to Close.")
+                                        contracts = int(float(r.get("Contracts") or 0))
+                                        premium = float(r.get("_premium") or 0)
+                                        update_short_option_position(user.id, sym, contracts, premium, "Buy", d, opt_type, exp, strike, fees=fees)
+                                        ok += 1
+                                    elif action == "Sell to Close":
+                                        exp = r.get("_exp")
+                                        strike = float(r.get("_strike") or 0)
+                                        opt_type = str(r.get("_type") or "CALL").upper()
+                                        if not exp:
+                                            fallback = _resolve_position_for_symbol(sym, long_by_symbol)
+                                            if fallback:
+                                                exp = fallback.get("exp")
+                                                strike = float(fallback.get("strike") or 0)
+                                                opt_type = fallback.get("type") or opt_type
+                                        if not exp:
+                                            raise ValueError("Missing expiration for Sell to Close.")
+                                        contracts = int(float(r.get("Contracts") or 0))
+                                        premium = float(r.get("_premium") or 0)
+                                        update_asset_position(user.id, sym, contracts, premium, "Sell", d, f"LEAP_{opt_type}", exp, strike, fees=fees)
+                                        ok += 1
+                                    elif action == "Roll":
+                                        exp = r.get("_exp")
+                                        strike = float(r.get("_strike") or 0)
+                                        opt_type = str(r.get("_type") or "CALL").upper()
+                                        if not exp:
+                                            fallback = _resolve_position_for_symbol(sym, short_by_symbol)
+                                            if fallback:
+                                                exp = fallback.get("exp")
+                                                strike = float(fallback.get("strike") or 0)
+                                                opt_type = fallback.get("type") or opt_type
+                                        if not exp:
+                                            raise ValueError("Missing expiration for Roll.")
+                                        contracts = int(float(r.get("Contracts to Roll") or 0))
+                                        btc_price = float(r.get("_btc") or 0)
+                                        new_premium = float(r.get("_new_premium") or 0)
+                                        new_strike = float(r.get("_new_strike") or 0)
+                                        new_exp = r.get("_new_exp") or nf
+                                        txg = uuid.uuid4().hex[:12]
+                                        update_short_option_position(user.id, sym, contracts, btc_price, "Buy", d, opt_type, exp, strike, fees=fees, txg=txg)
+                                        update_short_option_position(user.id, sym, contracts, new_premium, "Sell", d, opt_type, new_exp, new_strike, fees=0.0, txg=txg)
+                                        ok += 1
+                                    elif action == "Expire":
+                                        exp = r.get("_exp")
+                                        strike = float(r.get("_strike") or 0)
+                                        opt_type = str(r.get("_type") or "CALL").upper()
+                                        if not exp:
+                                            fallback = _resolve_position_for_symbol(sym, short_by_symbol)
+                                            if fallback:
+                                                exp = fallback.get("exp")
+                                                strike = float(fallback.get("strike") or 0)
+                                                opt_type = fallback.get("type") or opt_type
+                                        contracts = int(float(r.get("Contracts to Expire") or 0))
+                                        _bulk_expire_contracts(user, sym, exp, strike, opt_type, contracts)
+                                        ok += 1
+                                    elif action == "Assign":
+                                        exp = r.get("_exp")
+                                        strike = float(r.get("_strike") or 0)
+                                        opt_type = str(r.get("_type") or "CALL").upper()
+                                        if not exp:
+                                            fallback = _resolve_position_for_symbol(sym, short_by_symbol)
+                                            if fallback:
+                                                exp = fallback.get("exp")
+                                                strike = float(fallback.get("strike") or 0)
+                                                opt_type = fallback.get("type") or opt_type
+                                        contracts = int(float(r.get("Contracts to Assign") or 0))
+                                        _bulk_assign_contracts(user, sym, exp, strike, opt_type, contracts)
+                                        ok += 1
+
+                            except Exception as e:
+                                errors.append(f"{r.get('Ticker','')}: {e}")
+
+                        if errors:
+                            st.error("Some rows failed:")
+                            for e in errors[:20]:
+                                st.write("•", e)
+                        st.success(f"Submitted {ok} transactions.")
+                        st.session_state["bulk_review_open"] = False
+                        st.rerun()
+                with c2:
+                    if st.button("Cancel", type="secondary"):
+                        st.session_state["bulk_review_open"] = False
 
 
     except Exception as e:
         st.error('Bulk Entries page error (see details below).')
         st.exception(e)
 
 
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
 
EOF
)
