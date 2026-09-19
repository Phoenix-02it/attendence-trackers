from __future__ import annotations

from datetime import date
import re

import pandas as pd
import streamlit as st
from supabase import Client, create_client


# ------------------------------------------------------------
# APP CONFIG
# ------------------------------------------------------------
st.set_page_config(
    page_title="Attendance Tracker | Secure Subject-wise Attendance",
    page_icon="✅",
    layout="wide",
    initial_sidebar_state="auto",
)

MIN_ATTENDANCE = 75.0
APP_VERSION = "7.1"


# ------------------------------------------------------------
# SECRETS / CLIENTS
# ------------------------------------------------------------
def require_secret(name: str) -> str:
    """Read a Streamlit secret and fail with a clear setup message."""
    try:
        value = str(st.secrets[name]).strip()
    except Exception:
        value = ""

    placeholder_values = {
        "PASTE_YOUR_PUBLISHABLE_KEY",
        "PASTE_YOUR_SECRET_KEY",
        "YOUR_REAL_sb_publishable_KEY",
        "YOUR_REAL_sb_secret_KEY",
    }
    if not value or value in placeholder_values or value.startswith("PASTE_"):
        st.error(
            f"Missing or placeholder `{name}`. Add the real value to "
            "`.streamlit/secrets.toml` locally or to your deployment platform's secret settings."
        )
        st.stop()

    if name == "SUPABASE_URL" and not (
        value.startswith("https://") and ".supabase.co" in value
    ):
        st.error("`SUPABASE_URL` does not look like a valid Supabase project URL.")
        st.stop()

    if name == "SUPABASE_PUBLISHABLE_KEY" and not (
        value.startswith("sb_publishable_") or value.startswith("eyJ")
    ):
        st.error("`SUPABASE_PUBLISHABLE_KEY` does not look like a valid publishable/anon key.")
        st.stop()

    if name == "SUPABASE_SECRET_KEY" and not (
        value.startswith("sb_secret_") or value.startswith("eyJ")
    ):
        st.error("`SUPABASE_SECRET_KEY` does not look like a valid Supabase secret/service-role key.")
        st.stop()

    return value


# Load the two public connection settings once, after the validation helper exists.
SUPABASE_URL = require_secret("SUPABASE_URL")
SUPABASE_PUBLISHABLE_KEY = require_secret("SUPABASE_PUBLISHABLE_KEY")


def optional_secret(name: str, default: str = "") -> str:
    """Read an optional Streamlit secret without stopping the app."""
    try:
        value = str(st.secrets.get(name, default)).strip()
    except Exception:
        value = default
    return value


APP_BASE_URL = optional_secret("APP_BASE_URL", "")
if APP_BASE_URL:
    APP_BASE_URL = APP_BASE_URL.rstrip("/")
    valid_public_url = (
        APP_BASE_URL.startswith("https://")
        or APP_BASE_URL.startswith("http://localhost")
        or APP_BASE_URL.startswith("http://127.0.0.1")
    )
    if not valid_public_url:
        st.error(
            "`APP_BASE_URL` must start with https:// for a public deployment "
            "or http://localhost while testing locally."
        )
        st.stop()


def public_client() -> Client:
    # Never cache an authenticated Supabase client across Streamlit users.
    return create_client(SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY)


def admin_client() -> Client:
    # Called only for destructive account deletion. This key must remain server-side.
    secret_key = require_secret("SUPABASE_SECRET_KEY")
    return create_client(SUPABASE_URL, secret_key)


def clear_local_session() -> None:
    for key in ("access_token", "refresh_token", "user_id", "user_email"):
        st.session_state.pop(key, None)


def remember_session(auth_response) -> None:
    session = getattr(auth_response, "session", None)
    user = getattr(auth_response, "user", None)
    if session is not None:
        st.session_state["access_token"] = session.access_token
        st.session_state["refresh_token"] = session.refresh_token
    if user is not None:
        st.session_state["user_id"] = str(user.id)
        st.session_state["user_email"] = user.email or ""


def authenticated_client() -> tuple[Client, object | None]:
    client = public_client()
    access = st.session_state.get("access_token")
    refresh = st.session_state.get("refresh_token")
    if not access or not refresh:
        return client, None

    try:
        response = client.auth.set_session(access, refresh)
        remember_session(response)
        verified = client.auth.get_user()
        user = getattr(verified, "user", None)
        if user is None:
            clear_local_session()
            return client, None
        st.session_state["user_id"] = str(user.id)
        st.session_state["user_email"] = user.email or ""
        return client, user
    except Exception:
        clear_local_session()
        return client, None


# ------------------------------------------------------------
# AUTH HELPERS
# ------------------------------------------------------------
def password_is_strong(password: str) -> tuple[bool, str]:
    if len(password) < 10:
        return False, "Use at least 10 characters."
    if not re.search(r"[A-Z]", password):
        return False, "Add at least one uppercase letter."
    if not re.search(r"[a-z]", password):
        return False, "Add at least one lowercase letter."
    if not re.search(r"\d", password):
        return False, "Add at least one number."
    return True, ""


def valid_email(value: str) -> bool:
    return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value.strip()))


def log_auth_error(action: str, exc: Exception) -> None:
    # Raw errors stay in the server/VS Code terminal, not in the public UI.
    print(f"{action} ERROR: {type(exc).__name__}: {exc}", flush=True)


def friendly_auth_error(exc: Exception, action: str) -> str:
    """Return a useful public message without exposing secrets or user enumeration details."""
    text = str(exc).lower()

    if "email address not authorized" in text or "not authorized" in text and "email" in text:
        return (
            "Supabase could not send the confirmation email with its default mail service. "
            "For testing, use an email that belongs to your Supabase project team, or configure "
            "custom SMTP in Supabase Authentication → SMTP Settings."
        )
    if "rate limit" in text or "too many requests" in text or "over_email_send_rate_limit" in text:
        return "Too many authentication attempts. Wait at least 60 seconds, then try again."
    if "signup" in text and "disabled" in text:
        return "Email sign-up is disabled in Supabase. Enable the Email provider in Authentication settings."
    if "invalid api key" in text or "apikey" in text or "api key" in text:
        return (
            "The Supabase API key is invalid. Re-copy the project's publishable key into "
            "`.streamlit/secrets.toml` and restart Streamlit."
        )
    if "password" in text and action == "SIGNUP":
        return "Supabase rejected the password. Use at least 10 characters with uppercase, lowercase and a number."
    if "email" in text and ("invalid" in text or "unable to validate" in text):
        return "Supabase rejected the email address. Check the address and try again."
    if "email not confirmed" in text:
        return "Your email has not been confirmed yet. Open the confirmation email, then sign in."
    if "invalid login credentials" in text:
        return "Email or password is incorrect, or the email has not been confirmed yet."
    if "user already registered" in text:
        return "That account may already exist. Try signing in instead."
    if "database error saving new user" in text:
        return "Supabase Auth could not create the user. Check the Supabase Auth logs and project configuration."

    if action == "LOGIN":
        return "Sign in failed. Check your email, password, and email-confirmation status."
    if action == "SIGNUP":
        return "Account creation failed. The exact diagnostic has been written to the server terminal."
    return "Authentication request failed. Check the server terminal for the diagnostic."


def auth_screen() -> None:
    st.title("Attendance Tracker")
    st.caption("Secure subject-wise attendance, accessible from desktop and mobile browsers")

    login_tab, signup_tab = st.tabs(["Sign in", "Create account"])

    with login_tab:
        with st.form("login_form"):
            email = st.text_input("Email", placeholder="you@example.com")
            password = st.text_input("Password", type="password")
            submit = st.form_submit_button("Sign in", type="primary", width="stretch")

        if submit:
            email_clean = email.strip().lower()
            if not email_clean or not password:
                st.error("Enter your email and password.")
            elif not valid_email(email_clean):
                st.error("Enter a valid email address.")
            else:
                try:
                    client = public_client()
                    response = client.auth.sign_in_with_password(
                        {"email": email_clean, "password": password}
                    )
                    remember_session(response)
                    if getattr(response, "session", None) is None:
                        st.error("Sign in failed.")
                    else:
                        st.rerun()
                except Exception as exc:
                    log_auth_error("LOGIN", exc)
                    st.error(friendly_auth_error(exc, "LOGIN"))

    with signup_tab:
        st.caption(
            "Use an email you can access. Email confirmation should remain enabled in Supabase."
        )
        with st.form("signup_form"):
            display_name = st.text_input("Name", placeholder="Your name")
            email = st.text_input("Email", placeholder="you@example.com", key="signup_email")
            password = st.text_input("Password", type="password", key="signup_password")
            confirm = st.text_input("Confirm password", type="password")
            accepted = st.checkbox("I understand this account stores attendance data I create.")
            submit = st.form_submit_button(
                "Create account", type="primary", width="stretch"
            )

        if submit:
            email_clean = email.strip().lower()
            strong, reason = password_is_strong(password)

            if not display_name.strip() or not email_clean:
                st.error("Name and email are required.")
            elif not valid_email(email_clean):
                st.error("Enter a valid email address.")
            elif password != confirm:
                st.error("Passwords do not match.")
            elif not strong:
                st.error(reason)
            elif not accepted:
                st.error("Please confirm the data notice before creating the account.")
            else:
                try:
                    client = public_client()
                    response = client.auth.sign_up(
                        {
                            "email": email_clean,
                            "password": password,
                            "options": {
                                "data": {"display_name": display_name.strip()},
                                **(
                                    {"email_redirect_to": APP_BASE_URL}
                                    if APP_BASE_URL
                                    else {}
                                ),
                            },
                        }
                    )

                    if getattr(response, "session", None) is not None:
                        remember_session(response)
                        st.success("Account created.")
                        st.rerun()
                    else:
                        st.success(
                            "Account created. Check your email for the confirmation message, "
                            "confirm the address, then return here to sign in."
                        )
                except Exception as exc:
                    log_auth_error("SIGNUP", exc)
                    st.error(friendly_auth_error(exc, "SIGNUP"))

    with st.expander("Setup check", expanded=False):
        st.success("Supabase URL and publishable key were loaded successfully.")
        if APP_BASE_URL:
            st.success(f"Public app URL configured: {APP_BASE_URL}")
        else:
            st.info(
                "APP_BASE_URL is not set yet. That is fine for localhost testing. "
                "Set it to your final HTTPS address before public launch."
            )
        st.caption(
            "If sign-up fails, the exact Supabase diagnostic is printed only in the "
            "VS Code / server terminal. Secret values are never printed."
        )

    st.info(
        "Your attendance data is isolated by database Row Level Security. "
        "One signed-in account cannot read another account's students or attendance."
    )
    st.caption(f"App version {APP_VERSION}")
    st.caption(
        "Direct browser access works as soon as this app is deployed to an HTTPS host. "
        "Search-engine appearance is separate and can take time after deployment."
    )
    st.stop()


# ------------------------------------------------------------
# DATABASE HELPERS
# ------------------------------------------------------------
def table_df(client: Client, table: str, columns: list[str]) -> pd.DataFrame:
    response = client.table(table).select(",".join(columns)).execute()
    data = response.data or []
    return pd.DataFrame(data, columns=columns)


def students_df(client: Client) -> pd.DataFrame:
    df = table_df(client, "students", ["id", "student_code", "student_name", "student_email"])
    if not df.empty:
        df = df.sort_values(["student_name", "student_code"], kind="stable")
    return df


def subjects_df(client: Client) -> pd.DataFrame:
    df = table_df(client, "subjects", ["id", "subject_code", "subject_name"])
    if not df.empty:
        df = df.sort_values(["subject_name", "subject_code"], kind="stable")
    return df


def enrollments_df(client: Client) -> pd.DataFrame:
    return table_df(client, "enrollments", ["id", "tracking_id", "student_id", "subject_id"])


def sessions_df(client: Client) -> pd.DataFrame:
    df = table_df(client, "sessions", ["id", "subject_id", "session_date", "topic"])
    if not df.empty:
        df["session_date"] = df["session_date"].astype(str)
    return df


def attendance_df(client: Client) -> pd.DataFrame:
    return table_df(client, "attendance", ["id", "enrollment_id", "session_id", "status"])


def attendance_rate(present: int, absent: int) -> float | None:
    counted = present + absent
    if counted == 0:
        return None
    return present * 100.0 / counted


def rate_status(rate: float | None) -> str:
    if rate is None:
        return "No counted classes"
    return "Meets requirement" if rate >= MIN_ATTENDANCE else "Below 75%"


def human_tracking_id(value: str) -> str:
    compact = str(value).replace("-", "").upper()
    return f"AT-{compact[:16]}"


# ------------------------------------------------------------
# AUTH GATE
# ------------------------------------------------------------
client, current_user = authenticated_client()
if current_user is None:
    auth_screen()
    # In a normal Streamlit run, auth_screen() stops the script itself.
    # This explicit exit also protects against accidental execution with
    # `python attendance_tracker_web_v7_1.py` / VS Code's Run Python File.
    raise SystemExit

CURRENT_USER_ID = str(current_user.id)
CURRENT_EMAIL = current_user.email or ""


# ------------------------------------------------------------
# STYLING
# ------------------------------------------------------------
st.markdown(
    """
    <style>
    .block-container {
        padding-top: 1rem;
        padding-bottom: 2rem;
        max-width: 1250px;
    }

    div[data-testid="stMetric"] {
        border: 1px solid #e5e7eb;
        padding: 14px;
        border-radius: 12px;
    }

    button, [role="button"], input, textarea, select {
        min-height: 42px;
    }

    @media (max-width: 768px) {
        .block-container {
            padding-top: 0.6rem;
            padding-left: 0.8rem;
            padding-right: 0.8rem;
            padding-bottom: 1.5rem;
        }

        h1 { font-size: 1.7rem !important; }
        h2 { font-size: 1.35rem !important; }
        h3 { font-size: 1.15rem !important; }

        div[data-testid="stMetric"] {
            padding: 10px;
            border-radius: 10px;
        }

        div[data-testid="stDataFrame"] {
            overflow-x: auto;
        }

        button {
            width: 100%;
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ------------------------------------------------------------
# SIDEBAR
# ------------------------------------------------------------
with st.sidebar:
    st.title("Attendance")
    st.caption(f"Signed in as {CURRENT_EMAIL}")
    page = st.radio(
        "Menu",
        [
            "Dashboard",
            "Take Attendance",
            "Student Tracking",
            "Students",
            "Subjects & Enrollments",
            "Account",
        ],
    )
    st.divider()
    st.metric("Minimum required", f"{MIN_ATTENDANCE:.0f}%")
    st.caption("Excused classes are excluded from the percentage.")
    if APP_BASE_URL:
        st.caption("Public web mode enabled")
    else:
        st.caption("Local/test mode")
    st.caption(f"Version {APP_VERSION}")
    if st.button("Sign out", width="stretch"):
        try:
            client.auth.sign_out()
        except Exception:
            pass
        clear_local_session()
        st.rerun()


# ------------------------------------------------------------
# DASHBOARD
# ------------------------------------------------------------
if page == "Dashboard":
    st.title("Attendance Dashboard")
    st.caption("Only data belonging to your account is visible here.")

    students = students_df(client)
    subjects = subjects_df(client)
    sessions = sessions_df(client)
    enrollments = enrollments_df(client)
    attendance = attendance_df(client)

    c1, c2, c3 = st.columns(3)
    c1.metric("Students", len(students))
    c2.metric("Subjects", len(subjects))
    c3.metric("Classes recorded", len(sessions))

    st.divider()
    if subjects.empty:
        st.info("Add a subject first from 'Subjects & Enrollments'.")
    else:
        subject_map = {
            f"{r.subject_name} ({r.subject_code})": int(r.id)
            for r in subjects.itertuples()
        }
        label = st.selectbox("Subject", list(subject_map))
        subject_id = subject_map[label]

        current_enrollments = enrollments[enrollments["subject_id"] == subject_id].copy()
        if current_enrollments.empty:
            st.info("No students are enrolled in this subject yet.")
        else:
            student_lookup = students.set_index("id") if not students.empty else pd.DataFrame()
            rows = []
            for enr in current_enrollments.itertuples():
                student = student_lookup.loc[enr.student_id]
                records = attendance[attendance["enrollment_id"] == enr.id]
                present = int((records["status"] == "Present").sum())
                absent = int((records["status"] == "Absent").sum())
                excused = int((records["status"] == "Excused").sum())
                rate = attendance_rate(present, absent)
                rows.append(
                    {
                        "Tracking ID": human_tracking_id(enr.tracking_id),
                        "Student ID": student["student_code"],
                        "Student": student["student_name"],
                        "Present": present,
                        "Absent": absent,
                        "Excused": excused,
                        "Attendance %": None if rate is None else round(rate, 1),
                        "Status": rate_status(rate),
                    }
                )

            summary = pd.DataFrame(rows)
            at_risk = summary[
                summary["Attendance %"].notna() & (summary["Attendance %"] < MIN_ATTENDANCE)
            ]
            m1, m2 = st.columns(2)
            m1.metric("Enrolled students", len(summary))
            m2.metric("Below 75%", len(at_risk))
            st.dataframe(summary, width="stretch", hide_index=True)


# ------------------------------------------------------------
# TAKE ATTENDANCE
# ------------------------------------------------------------
elif page == "Take Attendance":
    st.title("Take Attendance")
    st.caption("One save operation writes the class and roster attendance atomically in PostgreSQL.")

    subjects = subjects_df(client)
    students = students_df(client)
    enrollments = enrollments_df(client)
    sessions = sessions_df(client)
    attendance = attendance_df(client)

    if subjects.empty:
        st.warning("Create a subject first.")
        st.stop()

    subject_map = {
        f"{r.subject_name} ({r.subject_code})": int(r.id)
        for r in subjects.itertuples()
    }
    subject_label = st.selectbox("Subject", list(subject_map))
    subject_id = subject_map[subject_label]

    current_enrollments = enrollments[enrollments["subject_id"] == subject_id].copy()
    if current_enrollments.empty:
        st.warning("No students are enrolled in this subject.")
        st.stop()

    student_lookup = students.set_index("id")
    roster = []
    for enr in current_enrollments.itertuples():
        student = student_lookup.loc[enr.student_id]
        roster.append(
            {
                "enrollment_id": int(enr.id),
                "tracking_id": enr.tracking_id,
                "student_code": student["student_code"],
                "student_name": student["student_name"],
            }
        )
    roster = sorted(roster, key=lambda x: (x["student_name"].lower(), x["student_code"]))

    session_date = st.date_input("Class date", value=date.today())

    same_day = sessions[
        (sessions["subject_id"] == subject_id)
        & (sessions["session_date"] == str(session_date))
    ].copy()

    options = ["Create new class"]
    session_lookup = {}
    if not same_day.empty:
        for row in same_day.sort_values("id", ascending=False).itertuples():
            option = f"Edit class #{int(row.id)} - {row.topic or 'No topic'}"
            options.append(option)
            session_lookup[option] = int(row.id)

    session_choice = st.selectbox("Class session", options)
    session_id = session_lookup.get(session_choice)

    saved_topic = ""
    if session_id is not None:
        row = same_day[same_day["id"] == session_id]
        if not row.empty:
            saved_topic = str(row.iloc[0]["topic"] or "")

    topic = st.text_input(
        "Topic",
        value=saved_topic,
        placeholder="Optional, e.g. Chapter 4",
        key=f"topic_{subject_id}_{session_date}_{session_id}",
    )

    existing = {}
    if session_id is not None:
        current_att = attendance[attendance["session_id"] == session_id]
        existing = {
            int(r.enrollment_id): r.status
            for r in current_att.itertuples()
        }
        row = same_day[same_day["id"] == session_id]
        if not row.empty and row.iloc[0]["topic"]:
            st.caption(f"Saved topic: {row.iloc[0]['topic']}")

    bulk = st.radio(
        "Quick mark",
        ["Keep individual selections", "Mark all Present", "Mark all Absent"],
        horizontal=True,
    )

    records = []
    with st.form("attendance_form"):
        st.subheader("Class roster")
        for row in roster:
            enrollment_id = row["enrollment_id"]
            default = existing.get(enrollment_id, "Present")
            if bulk == "Mark all Present":
                default = "Present"
            elif bulk == "Mark all Absent":
                default = "Absent"

            left, right = st.columns([3, 2])
            left.markdown(
                f"**{row['student_name']}**  \n"
                f"Student ID: `{row['student_code']}` · Tracking ID: `{human_tracking_id(row['tracking_id'])}`"
            )
            choices = ["Present", "Absent", "Excused"]
            status = right.radio(
                f"Status {enrollment_id}",
                choices,
                index=choices.index(default),
                horizontal=True,
                label_visibility="collapsed",
                key=f"status_{subject_id}_{session_id}_{enrollment_id}_{bulk}",
            )
            records.append({"enrollment_id": enrollment_id, "status": status})

        submitted = st.form_submit_button("Save Attendance", type="primary", width="stretch")

    if submitted:
        try:
            response = client.rpc(
                "save_attendance",
                {
                    "p_subject_id": subject_id,
                    "p_session_date": str(session_date),
                    "p_topic": topic.strip(),
                    "p_session_id": session_id,
                    "p_records": records,
                },
            ).execute()
            saved_id = response.data
            st.success(f"Attendance saved successfully for class #{saved_id}.")
            st.rerun()
        except Exception as exc:
            print(f"ATTENDANCE SAVE ERROR: {type(exc).__name__}: {exc}", flush=True)
            st.error("Attendance could not be saved. Check the server terminal for the diagnostic.")


# ------------------------------------------------------------
# STUDENT TRACKING
# ------------------------------------------------------------
elif page == "Student Tracking":
    st.title("Student Tracking")
    st.caption("Each student-subject enrollment has its own tracking ID and percentage.")

    students = students_df(client)
    subjects = subjects_df(client)
    enrollments = enrollments_df(client)
    sessions = sessions_df(client)
    attendance = attendance_df(client)

    if students.empty:
        st.info("No students have been added yet.")
        st.stop()

    student_map = {
        f"{r.student_name} ({r.student_code})": int(r.id)
        for r in students.itertuples()
    }
    label = st.selectbox("Student", list(student_map))
    student_id = student_map[label]

    current_enrollments = enrollments[enrollments["student_id"] == student_id]
    if current_enrollments.empty:
        st.info("This student is not enrolled in any subject.")
        st.stop()

    subject_lookup = subjects.set_index("id")
    session_lookup = sessions.set_index("id") if not sessions.empty else pd.DataFrame()

    for enr in current_enrollments.itertuples():
        subject = subject_lookup.loc[enr.subject_id]
        records = attendance[attendance["enrollment_id"] == enr.id]
        present = int((records["status"] == "Present").sum())
        absent = int((records["status"] == "Absent").sum())
        excused = int((records["status"] == "Excused").sum())
        rate = attendance_rate(present, absent)

        with st.container(border=True):
            st.subheader(f"{subject['subject_name']} ({subject['subject_code']})")
            st.caption(f"Tracking ID: {human_tracking_id(enr.tracking_id)}")
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Present", present)
            c2.metric("Absent", absent)
            c3.metric("Excused", excused)
            c4.metric("Attendance", "—" if rate is None else f"{rate:.1f}%")

            if rate is None:
                st.info("No counted attendance yet.")
            elif rate >= MIN_ATTENDANCE:
                st.success("75% requirement met.")
            else:
                st.error(f"Below the 75% requirement by {MIN_ATTENDANCE - rate:.1f} percentage points.")

            history_rows = []
            for rec in records.itertuples():
                if sessions.empty or rec.session_id not in session_lookup.index:
                    continue
                sess = session_lookup.loc[rec.session_id]
                history_rows.append(
                    {
                        "Date": sess["session_date"],
                        "Topic": sess["topic"] or "",
                        "Status": rec.status,
                    }
                )
            if history_rows:
                history = pd.DataFrame(history_rows).sort_values("Date", ascending=False)
                st.dataframe(history, width="stretch", hide_index=True)


# ------------------------------------------------------------
# STUDENTS
# ------------------------------------------------------------
elif page == "Students":
    st.title("Students")
    with st.form("add_student_form", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        student_code = c1.text_input("Student ID", placeholder="S1001")
        student_name = c2.text_input("Student name")
        student_email = c3.text_input("Email (optional)")
        add_student = st.form_submit_button("Add Student", type="primary")

    if add_student:
        if not student_code.strip() or not student_name.strip():
            st.error("Student ID and name are required.")
        else:
            try:
                client.table("students").insert(
                    {
                        "student_code": student_code.strip(),
                        "student_name": student_name.strip(),
                        "student_email": student_email.strip() or None,
                    }
                ).execute()
                st.success("Student added.")
                st.rerun()
            except Exception:
                st.error("That Student ID may already exist in your account.")

    st.divider()
    students = students_df(client)
    if students.empty:
        st.info("No students yet.")
    else:
        display = students.rename(
            columns={
                "student_code": "Student ID",
                "student_name": "Student",
                "student_email": "Email",
            }
        )[["Student ID", "Student", "Email"]]
        st.dataframe(display, width="stretch", hide_index=True)


# ------------------------------------------------------------
# SUBJECTS & ENROLLMENTS
# ------------------------------------------------------------
elif page == "Subjects & Enrollments":
    st.title("Subjects & Enrollments")
    tab_subjects, tab_enroll = st.tabs(["Subjects", "Enroll students"])

    with tab_subjects:
        with st.form("add_subject_form", clear_on_submit=True):
            c1, c2 = st.columns(2)
            subject_code = c1.text_input("Subject code", placeholder="MATH101")
            subject_name = c2.text_input("Subject name", placeholder="Calculus")
            add_subject = st.form_submit_button("Add Subject", type="primary")

        if add_subject:
            if not subject_code.strip() or not subject_name.strip():
                st.error("Subject code and name are required.")
            else:
                try:
                    client.table("subjects").insert(
                        {
                            "subject_code": subject_code.strip(),
                            "subject_name": subject_name.strip(),
                        }
                    ).execute()
                    st.success("Subject added.")
                    st.rerun()
                except Exception:
                    st.error("That subject code may already exist in your account.")

        subjects = subjects_df(client)
        if not subjects.empty:
            display = subjects.rename(
                columns={"subject_code": "Subject Code", "subject_name": "Subject"}
            )[["Subject Code", "Subject"]]
            st.dataframe(display, width="stretch", hide_index=True)

    with tab_enroll:
        students = students_df(client)
        subjects = subjects_df(client)
        enrollments = enrollments_df(client)

        if students.empty or subjects.empty:
            st.info("Add at least one student and one subject first.")
        else:
            student_map = {
                f"{r.student_name} ({r.student_code})": int(r.id)
                for r in students.itertuples()
            }
            subject_map = {
                f"{r.subject_name} ({r.subject_code})": int(r.id)
                for r in subjects.itertuples()
            }
            c1, c2 = st.columns(2)
            student_label = c1.selectbox("Student", list(student_map), key="enroll_student")
            subject_label = c2.selectbox("Subject", list(subject_map), key="enroll_subject")

            if st.button("Enroll Student", type="primary"):
                try:
                    client.table("enrollments").insert(
                        {
                            "student_id": student_map[student_label],
                            "subject_id": subject_map[subject_label],
                        }
                    ).execute()
                    st.success("Enrollment created with a unique attendance tracking ID.")
                    st.rerun()
                except Exception:
                    st.warning("This student may already be enrolled in that subject.")

            st.divider()
            enrollments = enrollments_df(client)
            if enrollments.empty:
                st.info("No enrollments yet.")
            else:
                student_lookup = students.set_index("id")
                subject_lookup = subjects.set_index("id")
                rows = []
                for enr in enrollments.itertuples():
                    student = student_lookup.loc[enr.student_id]
                    subject = subject_lookup.loc[enr.subject_id]
                    rows.append(
                        {
                            "Tracking ID": human_tracking_id(enr.tracking_id),
                            "Student ID": student["student_code"],
                            "Student": student["student_name"],
                            "Subject Code": subject["subject_code"],
                            "Subject": subject["subject_name"],
                        }
                    )
                st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)


# ------------------------------------------------------------
# ACCOUNT
# ------------------------------------------------------------
elif page == "Account":
    st.title("Account")
    st.caption("Authentication is handled by Supabase. Your app database does not store your password.")

    st.subheader("Security")
    st.write(f"Signed in email: **{CURRENT_EMAIL}**")
    if APP_BASE_URL:
        st.caption(f"Public app address: {APP_BASE_URL}")

    with st.expander("Change password"):
        with st.form("change_password_form"):
            current_password = st.text_input("Current password", type="password")
            new_password = st.text_input("New password", type="password")
            confirm_password = st.text_input("Confirm new password", type="password")
            change = st.form_submit_button("Change password")

        if change:
            strong, reason = password_is_strong(new_password)
            if new_password != confirm_password:
                st.error("New passwords do not match.")
            elif not strong:
                st.error(reason)
            else:
                try:
                    verify = public_client()
                    verify_response = verify.auth.sign_in_with_password(
                        {"email": CURRENT_EMAIL, "password": current_password}
                    )
                    verified_user = getattr(verify_response, "user", None)
                    if verified_user is None or str(verified_user.id) != CURRENT_USER_ID:
                        raise RuntimeError("Reauthentication failed")
                    # Password change is performed server-side only after the current password is verified.
                    admin = admin_client()
                    admin.auth.admin.update_user_by_id(
                        CURRENT_USER_ID, {"password": new_password}
                    )
                    clear_local_session()
                    st.success("Password changed. Please sign in again with your new password.")
                    st.rerun()
                except Exception as exc:
                    print(f"PASSWORD CHANGE ERROR: {type(exc).__name__}: {exc}", flush=True)
                    st.error("Current password is incorrect or the password could not be changed.")

    st.divider()
    st.subheader("Delete account")
    st.warning(
        "Permanent deletion removes your login plus all students, subjects, enrollments, classes and attendance records. "
        "This cannot be undone."
    )

    with st.form("delete_account_form"):
        delete_password = st.text_input("Re-enter your password", type="password")
        delete_phrase = st.text_input('Type exactly: DELETE MY ACCOUNT')
        delete_account = st.form_submit_button("Permanently delete my account", type="primary")

    if delete_account:
        if delete_phrase.strip() != "DELETE MY ACCOUNT":
            st.error("Confirmation phrase does not match.")
        else:
            try:
                # Reauthenticate before allowing the destructive admin operation.
                verify = public_client()
                verify_response = verify.auth.sign_in_with_password(
                    {"email": CURRENT_EMAIL, "password": delete_password}
                )
                verified_user = getattr(verify_response, "user", None)
                if verified_user is None or str(verified_user.id) != CURRENT_USER_ID:
                    raise RuntimeError("Reauthentication failed")

                # The secret key remains on the server. ON DELETE CASCADE removes owned app data.
                admin = admin_client()
                admin.auth.admin.delete_user(CURRENT_USER_ID)
                clear_local_session()
                st.success("Your account and attendance data have been permanently deleted.")
                st.rerun()
            except Exception as exc:
                print(f"ACCOUNT DELETE ERROR: {type(exc).__name__}: {exc}", flush=True)
                st.error("Account deletion failed. Check your password and server configuration.")
