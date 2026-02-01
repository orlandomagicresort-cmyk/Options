from types import SimpleNamespace
import streamlit as st

def _mask_name_before_at(name: str) -> str:
    s = (name or "").strip()
    if not s:
        return "Unknown"
    return s.split("@", 1)[0] if "@" in s else s

def ensure_user_preferences_row(sb, user):
    """Ensures a user_preferences row exists for this user."""
    try:
        uid = getattr(user, "id", None)
        email = (getattr(user, "email", "") or "").strip()
        if not uid:
            return
        existing = sb.table("user_preferences").select("display_name").eq("user_id", uid).execute().data or []
        if not existing:
            sb.table("user_preferences").insert({
                "user_id": uid,
                "display_name": email or None,
                "share_stats": False,
            }).execute()
        else:
            dn = (existing[0].get("display_name") or "").strip()
            if (not dn) and email:
                sb.table("user_preferences").update({"display_name": email}).eq("user_id", uid).execute()
    except Exception:
        pass

def activate_pending_invites(sb, user):
    try:
        email = (getattr(user, "email", "") or "").lower().strip()
        if not email:
            return
        pending = (
            sb.table("account_access")
              .select("id, delegate_user_id")
              .eq("delegate_email", email)
              .eq("status", "pending")
              .execute().data
            or []
        )
        for r in pending:
            if r.get("delegate_user_id"):
                continue
            try:
                sb.table("account_access").update({
                    "delegate_user_id": user.id,
                    "status": "active",
                }).eq("id", r["id"]).execute()
            except Exception:
                pass
    except Exception:
        pass

def get_accessible_accounts(sb, user):
    out = [{"label": "My Account", "owner_user_id": user.id, "role": "editor"}]
    try:
        email = (getattr(user, "email", "") or "").lower().strip()
        flt = f"delegate_user_id.eq.{user.id},delegate_email.eq.{email}" if email else None

        try:
            q = sb.table("account_access").select(
                "id, owner_user_id, role, status, delegate_user_id, delegate_email, owner_email"
            )
            q = q.or_(flt) if flt else q.eq("delegate_user_id", user.id)
            rows = q.execute().data or []
        except Exception:
            q = sb.table("account_access").select(
                "id, owner_user_id, role, status, delegate_user_id, delegate_email"
            )
            q = q.or_(flt) if flt else q.eq("delegate_user_id", user.id)
            rows = q.execute().data or []

        rows = [r for r in rows if (r.get("status") in ("active", "pending"))]
        owner_ids = [r["owner_user_id"] for r in rows if r.get("owner_user_id")]

        names = {}
        if owner_ids:
            prefs = sb.table("user_preferences").select("user_id, display_name").in_("user_id", owner_ids).execute().data or []
            for p in prefs:
                names[str(p.get("user_id"))] = p.get("display_name") or ""

        for r in rows:
            oid = r.get("owner_user_id")
            if not oid:
                continue
            nm = names.get(str(oid), "")
            masked = _mask_name_before_at(nm)

            if masked == "Unknown":
                oe = (r.get("owner_email") or "").strip()
                masked = _mask_name_before_at(oe)
            if masked == "Unknown":
                masked = f"acct {str(oid)[:8]}"

            label = f"Delegated ({masked})"
            if r.get("status") == "pending":
                label = f"{label} (pending)"

            role = (r.get("role") or "viewer")
            out.append({"label": label, "owner_user_id": oid, "role": role})
    except Exception:
        pass
    return out

def set_active_account(sb, user):
    ensure_user_preferences_row(sb, user)
    activate_pending_invites(sb, user)

    accts = get_accessible_accounts(sb, user)
    labels = [a["label"] for a in accts]

    cur = st.session_state.get("active_account_label") or labels[0]
    if cur not in labels:
        cur = labels[0]

    sel = st.sidebar.selectbox("Working on account", labels, index=labels.index(cur), key="account_selector")
    st.session_state["active_account_label"] = sel
    chosen = next(a for a in accts if a["label"] == sel)

    # fetch display name (optional)
    chosen_display = None
    try:
        prefs = sb.table("user_preferences").select("display_name").eq("user_id", chosen["owner_user_id"]).limit(1).execute().data or []
        if prefs:
            chosen_display = prefs[0].get("display_name")
    except Exception:
        chosen_display = None

    st.session_state["active_account_display_name"] = chosen_display
    st.session_state["active_user_id"] = chosen["owner_user_id"]
    st.session_state["active_role"] = chosen["role"]
    st.session_state["read_only"] = (chosen["owner_user_id"] != user.id and chosen["role"] != "editor")

    return SimpleNamespace(
        id=chosen["owner_user_id"],
        email=(chosen_display or getattr(user, "email", "")),
    )
