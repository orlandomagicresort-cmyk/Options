import streamlit as st
from supabase import create_client

from .config import SUPABASE_URL, SUPABASE_KEY

@st.cache_resource
def init_supabase():
    if not SUPABASE_URL or not SUPABASE_KEY:
        st.error("Missing Database Credentials! Please configure .streamlit/secrets.toml")
        st.stop()
    return create_client(SUPABASE_URL, SUPABASE_KEY)

def attach_user_jwt(sb):
    """Attach the logged-in user's JWT so PostgREST respects RLS."""
    token = st.session_state.get("access_token")
    if token:
        try:
            sb.postgrest.auth(token)
        except Exception:
            # older supabase-py compatibility
            pass

def require_editor():
    if st.session_state.get("read_only"):
        st.error("Read-only access: you don't have permission to modify this account.")
        st.stop()
