import streamlit as st

from src.db import init_supabase, attach_user_jwt
from src.context import set_active_account

st.set_page_config(page_title="Pro Options Tracker", layout="wide", initial_sidebar_state="expanded")

sb = init_supabase()

# 1) your existing auth flow should set st.session_state["user"] + ["access_token"]
#    move it into src/auth.py next — keep this minimal now.
user = st.session_state.get("user")
if not user:
    st.info("Please sign in.")
    st.stop()

attach_user_jwt(sb)

# 2) delegated account selector
active_user = set_active_account(sb, user)

# 3) Streamlit pages will pick up active user from session_state (active_user_id/read_only)
st.success(f"Active account: {st.session_state.get('active_account_label')}")
st.write("Use the left sidebar to navigate pages.")
