import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, date
import io
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Set page configuration
st.set_page_config(
    page_title="University Attendance Tracker & Alert System",
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="expanded"
)

DB_FILE = "attendance.db"

# -------------------------------------------------------------------------
# DATABASE UTILITIES & INITIALIZATION
# -------------------------------------------------------------------------

def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Create tables
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS courses (
        course_id TEXT PRIMARY KEY,
        course_name TEXT NOT NULL
    )
    ''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS students (
        student_id TEXT PRIMARY KEY,
        student_name TEXT NOT NULL,
        student_email TEXT UNIQUE
    )
    ''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS lectures (
        lecture_id INTEGER PRIMARY KEY AUTOINCREMENT,
        course_id TEXT NOT NULL,
        lecture_date TEXT NOT NULL,
        lecture_topic TEXT,
        live_checkin_active INTEGER DEFAULT 0,
        live_passcode TEXT,
        FOREIGN KEY (course_id) REFERENCES courses(course_id)
    )
    ''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS attendance (
        attendance_id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id TEXT NOT NULL,
        lecture_id INTEGER NOT NULL,
        status TEXT CHECK(status IN ('Present', 'Absent', 'Excused')),
        FOREIGN KEY (student_id) REFERENCES students(student_id),
        FOREIGN KEY (lecture_id) REFERENCES lectures(lecture_id),
        UNIQUE(student_id, lecture_id)
    )
    ''')
    
    conn.commit()
    
    # Check if database is empty to load mock data
    cursor.execute("SELECT COUNT(*) FROM students")
    if cursor.fetchone()[0] == 0:
        load_mock_data(conn)
        
    conn.close()

def load_mock_data(conn):
    cursor = conn.cursor()
    
    # Mock Courses
    courses = [
        ("CS101", "Introduction to Computer Science"),
        ("MATH201", "Linear Algebra"),
        ("ENG102", "Academic Writing")
    ]
    cursor.executemany("INSERT OR IGNORE INTO courses (course_id, course_name) VALUES (?, ?)", courses)
    
    # Mock Students
    students = [
        ("S1001", "Alice Smith", "alice.smith@university.edu"),
        ("S1002", "Bob Johnson", "bob.johnson@university.edu"),
        ("S1003", "Charlie Brown", "charlie.brown@university.edu"),
        ("S1004", "Diana Prince", "diana.prince@university.edu"),
        ("S1005", "Evan Wright", "evan.wright@university.edu"),
        ("S1006", "Fiona Gallagher", "fiona.g@university.edu"),
        ("S1007", "George Cooper", "george.c@university.edu"),
        ("S1008", "Hannah Abbott", "hannah.a@university.edu"),
        ("S1009", "Ian Malcolm", "ian.m@university.edu"),
        ("S1010", "Julia Roberts", "julia.r@university.edu")
    ]
    cursor.executemany("INSERT OR IGNORE INTO students (student_id, student_name, student_email) VALUES (?, ?, ?)", students)
    
    # Mock Lectures for CS101 & MATH201
    lectures = [
        ("CS101", "2026-09-01", "Introduction & Syllabus"),
        ("CS101", "2026-09-03", "Python Basics: Variables and Loops"),
        ("CS101", "2026-09-08", "Data Structures: Lists and Dicts"),
        ("MATH201", "2026-09-02", "Vectors and Matrices"),
        ("MATH201", "2026-09-07", "Matrix Multiplication")
    ]
    
    for course_id, l_date, topic in lectures:
        cursor.execute("INSERT INTO lectures (course_id, lecture_date, lecture_topic) VALUES (?, ?, ?)", (course_id, l_date, topic))
        lecture_id = cursor.lastrowid
        
        # Load mock attendance for each lecture (randomized slightly)
        for i, (student_id, _, _) in enumerate(students):
            if (i + int(lecture_id)) % 6 == 0:
                status = "Absent"
            elif (i + int(lecture_id)) % 11 == 0:
                status = "Excused"
            else:
                status = "Present"
            
            cursor.execute("INSERT OR IGNORE INTO attendance (student_id, lecture_id, status) VALUES (?, ?, ?)", (student_id, lecture_id, status))
            
    conn.commit()

# Initialize the database
init_db()

# -------------------------------------------------------------------------
# HELPER DATA QUERIES
# -------------------------------------------------------------------------

def query_dataframe(query, params=()):
    conn = get_db_connection()
    df = pd.read_sql_query(query, conn, params=params)
    conn.close()
    return df

def run_transaction(query, params=()):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(query, params)
        conn.commit()
        success = True
    except sqlite3.Error as e:
        st.error(f"Database Error: {e}")
        conn.rollback()
        success = False
    finally:
        conn.close()
    return success

# -------------------------------------------------------------------------
# EMAIL SYSTEM UTILITY (REAL SMTP & SIMULATED SANDBOX)
# -------------------------------------------------------------------------

def send_alert_email(to_email, student_name, course_id, rate, config):
    subject = f"⚠️ WARNING: Low Attendance Alert in {course_id}"
    
    body = f"""Dear {student_name},

This is an automated notification regarding your attendance in course {course_id}.

Our records show that your current attendance rate is {rate:.1f}%. 
Under university regulations, you are required to maintain a minimum of 75.0% attendance in order to sit for the final examinations.

You are currently falling below this threshold. Please reach out to your instructor as soon as possible to discuss how to make up for missed classes.

Sincerely,
Academic Administration & Portal Services
"""

    if config["mode"] == "Simulated Sandbox (No Mail Server Needed)":
        return True, f"SIMULATED: Email successfully drafted and 'sent' to {to_email}.\nSubject: {subject}\n"
    
    # Real SMTP Delivery
    try:
        msg = MIMEMultipart()
        msg['From'] = config["sender"]
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))
        
        server = smtplib.SMTP(config["host"], config["port"])
        server.starttls()
        server.login(config["sender"], config["password"])
        server.send_mail(config["sender"], [to_email], msg.as_string())
        server.quit()
        return True, f"REAL EMAIL: Successfully dispatched warning message to {to_email} via {config['host']}."
    except Exception as e:
        return False, f"REAL EMAIL FAILED: Could not deliver email to {to_email}. Error: {str(e)}"

# -------------------------------------------------------------------------
# SIDEBAR NAVIGATION & PORTAL SELECTOR
# -------------------------------------------------------------------------

with st.sidebar:
    st.image("https://images.unsplash.com/photo-1523050854058-8df90110c9f1?q=80&w=200&auto=format&fit=crop", caption="University Administration System")
    st.title("Attendance Portal")
    
    # Role Selector (Simulated Authentication Switch)
    user_role = st.selectbox(
        "🔓 Select Portal Access",
        ["👨‍🏫 Instructor View", "🧑‍🎓 Student View"]
    )
    
    st.divider()
    
    # Dynamic navigation options based on selected role
    if user_role == "👨‍🏫 Instructor View":
        menu = st.radio(
            "Dashboard Options:",
            ["📈 Metrics & Overview", "📝 Take Attendance", "🗂️ Attendance History", "📧 Alert & Notifications", "🧑‍🎓 Student Directory", "⚙️ Manage Roster"]
        )
    else:
        menu = st.radio(
            "My Portal Options:",
            ["📊 View My Attendance", "✏️ Edit My Profile", "📲 Self-Check-In"]
        )
        
    st.divider()
    st.info("💡 **Required Threshold:** University regulations mandate a minimum of **75% lecture attendance** per course to sit examinations.")

# -------------------------------------------------------------------------
# ROLE: STUDENT VIEW
# -------------------------------------------------------------------------

if user_role == "🧑‍🎓 Student View":
    # Simple simulated authentication check
    students_df = query_dataframe("SELECT * FROM students ORDER BY student_name")
    
    if students_df.empty:
        st.warning("No student records available in the database. Please ask your system administrator to register you first.")
    else:
        student_dict = {f"{row['student_name']} ({row['student_id']})": row['student_id'] for _, row in students_df.iterrows()}
        selected_login = st.selectbox("🔑 Sign In as Student", list(student_dict.keys()))
        logged_student_id = student_dict[selected_login]
        
        # Load logged-in student records
        student_details = query_dataframe("SELECT * FROM students WHERE student_id = ?", (logged_student_id,)).iloc[0]
        
        # ----------------- Tab: View My Attendance -----------------
        if menu == "📊 View My Attendance":
            st.title(f"📊 Personal Attendance Dashboard: {student_details['student_name']}")
            st.markdown("Monitor your class-by-class attendance, view lecture topics, and track threshold compliance.")
            
            # Fetch individual stats for each registered course
            ind_metrics = query_dataframe("""
                SELECT 
                    l.course_id, c.course_name,
                    SUM(CASE WHEN a.status = 'Present' THEN 1 ELSE 0 END) as present,
                    SUM(CASE WHEN a.status = 'Absent' THEN 1 ELSE 0 END) as absent,
                    SUM(CASE WHEN a.status = 'Excused' THEN 1 ELSE 0 END) as excused,
                    COUNT(a.attendance_id) as total,
                    (SUM(CASE WHEN a.status = 'Present' THEN 1 ELSE 0 END) * 100.0 / COUNT(a.attendance_id)) as rate
                FROM attendance a
                JOIN lectures l ON a.lecture_id = l.lecture_id
                JOIN courses c ON l.course_id = c.course_id
                WHERE a.student_id = ?
                GROUP BY l.course_id
            """, (logged_student_id,))
            
            if ind_metrics.empty:
                st.info("No attendance sessions have been logged for your profile yet.")
            else:
                # Summary Columns
                for _, course in ind_metrics.iterrows():
                    with st.container():
                        st.subheader(f"📚 {course['course_id']} - {course['course_name']}")
                        col_m1, col_m2, col_m3, col_m4 = st.columns(4)
                        
                        col_m1.metric("Registered Sessions", course['total'])
                        col_m2.metric("Attended Classes", course['present'])
                        
                        rate_val = course['rate']
                        if rate_val >= 75.0:
                            col_m3.metric("Your Attendance Rate", f"{rate_val:.1f}%", f"+{rate_val-75:.1f}% Above Limit")
                            col_m4.success("✅ COMPLIANT: You are clear to take examinations.")
                        else:
                            col_m3.metric("Your Attendance Rate", f"{rate_val:.1f}%", f"{rate_val-75:.1f}% Below Threshold", delta_color="inverse")
                            col_m4.error("⚠️ WARNING: You are currently barred from taking examinations.")
                        st.divider()
                        
                # Detailed Timeline
                st.subheader("🗓️ Full Attendance Timeline")
                timeline_df = query_dataframe("""
                    SELECT l.lecture_date as 'Date', l.course_id as 'Course',
                           l.lecture_topic as 'Topic', a.status as 'Status'
                    FROM attendance a
                    JOIN lectures l ON a.lecture_id = l.lecture_id
                    WHERE a.student_id = ?
                    ORDER BY l.lecture_date DESC
                """, (logged_student_id,))
                
                st.dataframe(timeline_df, use_container_width=True)

        # ----------------- Tab: Edit My Profile -----------------
        elif menu == "✏️ Edit My Profile":
            st.title("✏️ Edit Student Profile Details")
            st.markdown("Keep your administrative records up to date. Updating your profile instantly syncs your records across the directory.")
            
            with st.form("edit_profile_form"):
                new_name = st.text_input("Full Name", value=student_details['student_name'])
                new_email = st.text_input("Institutional Email Address", value=student_details['student_email'])
                
                submit_edit = st.form_submit_button("Update Profile Information", type="primary")
                
                if submit_edit:
                    if new_name.strip() and new_email.strip():
                        success = run_transaction(
                            "UPDATE students SET student_name = ?, student_email = ? WHERE student_id = ?",
                            (new_name.strip(), new_email.strip(), logged_student_id)
                        )
                        if success:
                            st.success("🎉 Profile information updated successfully. Refreshing portal...")
                            st.rerun()
                    else:
                        st.error("Fields cannot be left blank.")

        # ----------------- Tab: Self-Check-In -----------------
        elif menu == "📲 Self-Check-In":
            st.title("📲 Student Self-Check-In Portal")
            st.markdown("Mark yourself present for active class lectures by entering the validation passcode provided by your instructor.")
            
            # Fetch active check-in sessions
            active_sessions = query_dataframe("""
                SELECT l.lecture_id, l.course_id, c.course_name, l.lecture_date, l.lecture_topic
                FROM lectures l
                JOIN courses c ON l.course_id = c.course_id
                WHERE l.live_checkin_active = 1
            """)
            
            if active_sessions.empty:
                st.info("No live check-in sessions are currently active. Please wait for your instructor to launch a check-in.")
            else:
                st.success(f"🔥 {len(active_sessions)} live check-in sessions found!")
                
                for _, session in active_sessions.iterrows():
                    with st.container():
                        st.subheader(f"📚 {session['course_id']} - {session['lecture_topic']}")
                        st.markdown(f"**Date**: {session['lecture_date']} | **Course Title**: {session['course_name']}")
                        
                        # Form for passcode entry
                        with st.form(key=f"checkin_form_{session['lecture_id']}"):
                            passcode_input = st.text_input("Enter 4-Digit Passcode", max_chars=10, type="password", help="Get this passcode directly from your instructor.")
                            submit_checkin = st.form_submit_button("Mark Myself Present")
                            
                            if submit_checkin:
                                # Retrieve correct passcode to verify
                                db_session = query_dataframe("SELECT live_passcode FROM lectures WHERE lecture_id = ?", (session['lecture_id'],))
                                correct_passcode = db_session.iloc[0]['live_passcode'] if not db_session.empty else ""
                                
                                if passcode_input.strip() == correct_passcode:
                                    # Write or update attendance entry to "Present"
                                    success = run_transaction("""
                                        INSERT INTO attendance (student_id, lecture_id, status)
                                        VALUES (?, ?, 'Present')
                                        ON CONFLICT(student_id, lecture_id) DO UPDATE SET status='Present'
                                    """, (logged_student_id, session['lecture_id']))
                                    
                                    if success:
                                        st.success("🎉 Checked in successfully! Your attendance has been logged as **Present**.")
                                        st.balloons()
                                else:
                                    st.error("❌ Incorrect passcode. Please check with your instructor and try again.")

# -------------------------------------------------------------------------
# ROLE: INSTRUCTOR VIEW
# -------------------------------------------------------------------------

else:
    # ----------------- Tab: Metrics & Overview -----------------
    if menu == "📈 Metrics & Overview":
        st.title("📈 Course Attendance Dashboard")
        st.markdown("Real-time monitoring of attendance rates, student risk metrics, and class performance.")
        
        # Select Course
        courses_df = query_dataframe("SELECT * FROM courses")
        course_list = ["All Courses"] + courses_df["course_id"].tolist()
        selected_course = st.selectbox("Filter Dashboard by Course", course_list)
        
        # Formulate queries based on selection
        if selected_course == "All Courses":
            students_count = query_dataframe("SELECT COUNT(*) as count FROM students").iloc[0]["count"]
            lectures_count = query_dataframe("SELECT COUNT(*) as count FROM lectures").iloc[0]["count"]
            
            att_query = "SELECT status, COUNT(*) as count FROM attendance GROUP BY status"
            att_df = query_dataframe(att_query)
            
            history_query = """
                SELECT l.lecture_date, l.course_id,
                       SUM(CASE WHEN a.status = 'Present' THEN 1 ELSE 0 END) * 100.0 / COUNT(a.student_id) as att_rate
                FROM lectures l
                JOIN attendance a ON l.lecture_id = a.lecture_id
                GROUP BY l.lecture_id
                ORDER BY l.lecture_date ASC
            """
            history_df = query_dataframe(history_query)
            
            student_stats_query = """
                SELECT s.student_id, s.student_name,
                       SUM(CASE WHEN a.status = 'Present' THEN 1 ELSE 0 END) * 100.0 / COUNT(a.lecture_id) as rate
                FROM students s
                JOIN attendance a ON s.student_id = a.student_id
                GROUP BY s.student_id
            """
            student_stats_df = query_dataframe(student_stats_query)
            
        else:
            students_count = query_dataframe("SELECT COUNT(*) as count FROM students").iloc[0]["count"]
            lectures_count = query_dataframe("SELECT COUNT(*) as count FROM lectures WHERE course_id = ?", (selected_course,)).iloc[0]["count"]
            
            att_query = """
                SELECT a.status, COUNT(*) as count 
                FROM attendance a
                JOIN lectures l ON a.lecture_id = l.lecture_id
                WHERE l.course_id = ?
                GROUP BY a.status
            """
            att_df = query_dataframe(att_query, (selected_course,))
            
            history_query = """
                SELECT l.lecture_date, l.course_id,
                       SUM(CASE WHEN a.status = 'Present' THEN 1 ELSE 0 END) * 100.0 / COUNT(a.student_id) as att_rate
                FROM lectures l
                JOIN attendance a ON l.lecture_id = a.lecture_id
                WHERE l.course_id = ?
                GROUP BY l.lecture_id
                ORDER BY l.lecture_date ASC
            """
            history_df = query_dataframe(history_query, (selected_course,))
            
            student_stats_query = """
                SELECT s.student_id, s.student_name,
                       SUM(CASE WHEN a.status = 'Present' THEN 1 ELSE 0 END) * 100.0 / COUNT(a.lecture_id) as rate
                FROM students s
                JOIN attendance a ON s.student_id = a.student_id
                JOIN lectures l ON a.lecture_id = l.lecture_id
                WHERE l.course_id = ?
                GROUP BY s.student_id
            """
            student_stats_df = query_dataframe(student_stats_query, (selected_course,))

        # Calculate overall stats
        total_records = att_df["count"].sum() if not att_df.empty else 0
        presents = att_df[att_df["status"] == "Present"]["count"].sum() if not att_df.empty and "Present" in att_df["status"].values else 0
        excused = att_df[att_df["status"] == "Excused"]["count"].sum() if not att_df.empty and "Excused" in att_df["status"].values else 0
        absents = att_df[att_df["status"] == "Absent"]["count"].sum() if not att_df.empty and "Absent" in att_df["status"].values else 0
        
        overall_rate = (presents / (total_records - excused)) * 100 if (total_records - excused) > 0 else 0.0
        
        # At-Risk calculation (<75% attendance)
        at_risk_df = student_stats_df[student_stats_df["rate"] < 75.0] if not student_stats_df.empty else pd.DataFrame()
        at_risk_count = len(at_risk_df)
        
        # Display KPIs
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric(label="Total Students Enrolled", value=students_count)
        with col2:
            st.metric(label="Lectures Conducted", value=lectures_count)
        with col3:
            st.metric(label="Overall Attendance Rate", value=f"{overall_rate:.1f}%", delta=f"{overall_rate - 75:.1f}% vs Goal" if total_records > 0 else None)
        with col4:
            st.metric(label="Students At Risk (<75%)", value=at_risk_count, delta=f"{-at_risk_count} warning(s)" if at_risk_count == 0 else "Needs Attention", delta_color="inverse")
            
        st.divider()
        
        # Layout with Charts and Alerts
        chart_col, alert_col = st.columns([2, 1])
        
        with chart_col:
            st.subheader("Attendance Rate Over Time (%)")
            if not history_df.empty:
                history_df['lecture_date'] = pd.to_datetime(history_df['lecture_date'])
                chart_data = history_df.set_index('lecture_date')['att_rate']
                st.line_chart(chart_data, color="#0068c9")
            else:
                st.info("No attendance history matches your filter.")
                
        with alert_col:
            st.subheader("⚠️ At Risk Students (<75%)")
            if not at_risk_df.empty:
                st.warning(f"The following {len(at_risk_df)} students are falling below the university mandate:")
                for index, row in at_risk_df.iterrows():
                    st.error(f"**{row['student_name']}** ({row['student_id']}) — **{row['rate']:.1f}%**")
            else:
                st.success("🎉 Excellent! No students are currently below the 75% requirement.")

    # ----------------- Tab: Take Attendance -----------------
    elif menu == "📝 Take Attendance":
        st.title("📝 Log Class Attendance & Set Self-Check-In")
        st.markdown("Record daily records or activate a passcode validation session for self-check-ins.")
        
        take_tab, checkin_control_tab = st.tabs(["Check Roster Manually", "Student Self-Check-In Controller"])
        
        # Select Course & Date (Common Params)
        courses_df = query_dataframe("SELECT * FROM courses")
        if courses_df.empty:
            st.error("No courses available. Please add courses in 'Manage Roster' first.")
        else:
            course_options = {row['course_name']: row['course_id'] for _, row in courses_df.iterrows()}
            
            with take_tab:
                col_sel1, col_sel2 = st.columns(2)
                with col_sel1:
                    selected_course_name = st.selectbox("Select Course Record", list(course_options.keys()), key="man_course")
                    selected_course_id = course_options[selected_course_name]
                with col_sel2:
                    lecture_date = st.date_input("Session Date", date.today(), key="man_date")
                    
                # Setup lecture choice (New or Historical Update)
                existing_lectures = query_dataframe(
                    "SELECT lecture_id, lecture_topic, lecture_date FROM lectures WHERE course_id = ? AND lecture_date = ?", 
                    (selected_course_id, str(lecture_date))
                )
                
                is_new_lecture = True
                lecture_id = None
                topic = ""
                
                if not existing_lectures.empty:
                    options_dict = {"Create a NEW class session / lecture": "new"}
                    for _, row in existing_lectures.iterrows():
                        options_dict[f"Update Existing: '{row['lecture_topic']}' (ID: {row['lecture_id']})"] = row['lecture_id']
                        
                    session_choice = st.radio("Session Choice", list(options_dict.keys()), key="man_choice")
                    choice_val = options_dict[session_choice]
                    
                    if choice_val != "new":
                        is_new_lecture = False
                        lecture_id = choice_val
                        topic = existing_lectures[existing_lectures['lecture_id'] == lecture_id]['lecture_topic'].values[0]
                        
                if is_new_lecture:
                    topic = st.text_input("Lecture Topic (e.g., Intro to Arrays, Lab Session)", placeholder="Enter details...", key="man_topic")
                else:
                    st.info(f"Updating historical session: **{topic}** on {lecture_date}")
                    
                st.divider()
                
                # Load student lists
                students_df = query_dataframe("SELECT student_id, student_name, student_email FROM students ORDER BY student_name")
                
                if students_df.empty:
                    st.warning("No student records available. Please register students first.")
                else:
                    st.subheader("Roster Check")
                    s_col1, s_col2, s_col3 = st.columns([1, 1, 4])
                    mark_all_present = s_col1.button("Mark All Present")
                    mark_all_absent = s_col2.button("Mark All Absent")
                    
                    # If updating, load logged records
                    current_status = {}
                    if not is_new_lecture:
                        att_records = query_dataframe(
                            "SELECT student_id, status FROM attendance WHERE lecture_id = ?", 
                            (int(lecture_id),)
                        )
                        current_status = {row['student_id']: row['status'] for _, row in att_records.iterrows()}
                        
                    # Render roster status selections
                    updated_attendance = {}
                    header_col1, header_col2, header_col3 = st.columns([2, 3, 3])
                    header_col1.markdown("**Student ID / Name**")
                    header_col2.markdown("**Status Selector**")
                    header_col3.markdown("**Email**")
                    st.divider()
                    
                    for index, student in students_df.iterrows():
                        std_id = student['student_id']
                        std_name = student['student_name']
                        std_email = student['student_email']
                        
                        default_index = 0
                        if mark_all_present:
                            default_index = 0
                        elif mark_all_absent:
                            default_index = 1
                        elif std_id in current_status:
                            stat = current_status[std_id]
                            if stat == "Present":
                                default_index = 0
                            elif stat == "Absent":
                                default_index = 1
                            else:
                                default_index = 2
                                
                        col1, col2, col3 = st.columns([2, 3, 3])
                        col1.write(f"**{std_name}**  \n`{std_id}`")
                        status_option = col2.radio(
                            f"Status for {std_name}",
                            ["Present", "Absent", "Excused"],
                            index=default_index,
                            key=f"status_{std_id}",
                            horizontal=True,
                            label_visibility="collapsed"
                        )
                        updated_attendance[std_id] = status_option
                        col3.write(std_email)
                        
                    st.divider()
                    
                    if st.button("Submit & Save Attendance Logs", type="primary", key="man_submit"):
                        conn = get_db_connection()
                        cursor = conn.cursor()
                        try:
                            if is_new_lecture:
                                cursor.execute(
                                    "INSERT INTO lectures (course_id, lecture_date, lecture_topic) VALUES (?, ?, ?)",
                                    (selected_course_id, str(lecture_date), topic)
                                )
                                lecture_id = cursor.lastrowid
                                
                            for std_id, status_val in updated_attendance.items():
                                cursor.execute("""
                                    INSERT INTO attendance (student_id, lecture_id, status)
                                    VALUES (?, ?, ?)
                                    ON CONFLICT(student_id, lecture_id) DO UPDATE SET status=excluded.status
                                """, (std_id, lecture_id, status_val))
                                
                            conn.commit()
                            st.success("🎉 Attendance records successfully saved to local database!")
                            st.balloons()
                        except sqlite3.Error as e:
                            conn.rollback()
                            st.error(f"Failed to record attendance: {e}")
                        finally:
                            conn.close()

            with checkin_control_tab:
                st.subheader("📡 Live Student Self-Check-In Dashboard")
                st.markdown("Set up a self-check-in portal with a timed passcode. Students can instantly check themselves in on their device.")
                
                con_col1, con_col2 = st.columns(2)
                with con_col1:
                    live_course_name = st.selectbox("Select Course Record", list(course_options.keys()), key="live_course")
                    live_course_id = course_options[live_course_name]
                with con_col2:
                    live_date = st.date_input("Session Date", date.today(), key="live_date")
                    
                live_topic = st.text_input("Lecture Topic (e.g. Passcode verification validation)", "Standard Lecture Class", key="live_topic")
                passcode = st.text_input("Set 4-Digit Passcode (e.g. 5493)", max_chars=10, placeholder="Required passcode", key="passcode_set")
                
                # Check current live sessions
                current_active = query_dataframe("SELECT * FROM lectures WHERE live_checkin_active = 1")
                
                col_act1, col_act2 = st.columns(2)
                
                if current_active.empty:
                    if col_act1.button("🟢 Activate Live Check-In", type="primary"):
                        if passcode.strip() == "":
                            st.error("Please specify a 4-digit numeric passcode to activate live verification.")
                        else:
                            # Insert lecture, set live checkin code
                            conn = get_db_connection()
                            cursor = conn.cursor()
                            try:
                                cursor.execute("""
                                    INSERT INTO lectures (course_id, lecture_date, lecture_topic, live_checkin_active, live_passcode)
                                    VALUES (?, ?, ?, 1, ?)
                                """, (live_course_id, str(live_date), live_topic, passcode.strip()))
                                conn.commit()
                                st.success("📡 Self check-in launched! Students can now mark themselves present using the passcode.")
                                st.rerun()
                            except sqlite3.Error as e:
                                st.error(f"Database error: {e}")
                            finally:
                                conn.close()
                else:
                    active_lecture_id = current_active.iloc[0]['lecture_id']
                    st.info(f"📡 **Active Check-In Session**: {current_active.iloc[0]['course_id']} - {current_active.iloc[0]['lecture_topic']} (Passcode: `{current_active.iloc[0]['live_passcode']}`)")
                    
                    if col_act2.button("🔴 Deactivate Live Check-In", type="secondary"):
                        # Deactivate, mark absent for anyone who didn't check in
                        conn = get_db_connection()
                        cursor = conn.cursor()
                        try:
                            # Disable live status
                            cursor.execute("UPDATE lectures SET live_checkin_active = 0 WHERE lecture_id = ?", (active_lecture_id,))
                            
                            # Auto-mark missing student records as ABSENT (Positive vs Negative database rule)
                            # Fetch students not checked in
                            cursor.execute("""
                                INSERT INTO attendance (student_id, lecture_id, status)
                                SELECT s.student_id, ?, 'Absent'
                                FROM students s
                                WHERE s.student_id NOT IN (
                                    SELECT student_id FROM attendance WHERE lecture_id = ?
                                )
                            """, (active_lecture_id, active_lecture_id))
                            
                            conn.commit()
                            st.success("🔴 Live check-in completed. All unchecked student profiles marked as 'Absent'.")
                            st.rerun()
                        except sqlite3.Error as e:
                            st.error(f"Failed to complete session: {e}")
                        finally:
                            conn.close()

    # ----------------- Tab: Attendance History -----------------
    elif menu == "🗂️ Attendance History":
        st.title("🗂️ View and Export Historical Logs")
        st.markdown("Inspect existing attendance matrices and download comprehensive Excel reports.")
        
        courses_df = query_dataframe("SELECT * FROM courses")
        if courses_df.empty:
            st.warning("No courses available to display historical data.")
        else:
            course_options = {row['course_name']: row['course_id'] for _, row in courses_df.iterrows()}
            selected_course_name = st.selectbox("Select Course for Detailed History", list(course_options.keys()))
            selected_course_id = course_options[selected_course_name]
            
            lectures_list = query_dataframe(
                "SELECT lecture_id, lecture_date, lecture_topic FROM lectures WHERE course_id = ? ORDER BY lecture_date",
                (selected_course_id,)
            )
            
            if lectures_list.empty:
                st.info("No lectures have been logged for this course yet.")
            else:
                matrix_data = query_dataframe("""
                    SELECT s.student_id, s.student_name, l.lecture_date || ' (' || l.lecture_topic || ')' as lecture_label, a.status
                    FROM students s
                    CROSS JOIN lectures l
                    LEFT JOIN attendance a ON s.student_id = a.student_id AND l.lecture_id = a.lecture_id
                    WHERE l.course_id = ?
                    ORDER BY s.student_name, l.lecture_date
                """, (selected_course_id,))
                
                if not matrix_data.empty:
                    pivot_df = matrix_data.pivot(index=['student_id', 'student_name'], columns='lecture_label', values='status').reset_index()
                    pivot_df = pivot_df.fillna("Unmarked")
                    
                    st.subheader("Attendance Matrix View")
                    st.dataframe(pivot_df, use_container_width=True)
                    
                    st.subheader("Summary Table")
                    summary_data = query_dataframe("""
                        SELECT s.student_id as 'ID', s.student_name as 'Name',
                               SUM(CASE WHEN a.status = 'Present' THEN 1 ELSE 0 END) as 'Present Count',
                               SUM(CASE WHEN a.status = 'Absent' THEN 1 ELSE 0 END) as 'Absent Count',
                               SUM(CASE WHEN a.status = 'Excused' THEN 1 ELSE 0 END) as 'Excused Count',
                               COUNT(l.lecture_id) as 'Total Classes',
                               (SUM(CASE WHEN a.status = 'Present' THEN 1 ELSE 0 END) * 100.0 / COUNT(l.lecture_id)) as 'Attendance %'
                        FROM students s
                        JOIN attendance a ON s.student_id = a.student_id
                        JOIN lectures l ON a.lecture_id = l.lecture_id
                        WHERE l.course_id = ?
                        GROUP BY s.student_id
                        ORDER BY s.student_name
                    """, (selected_course_id,))
                    
                    st.dataframe(summary_data, use_container_width=True)
                    
                    st.subheader("📥 Export Data")
                    
                    buffer = io.BytesIO()
                    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                        pivot_df.to_excel(writer, sheet_name="Attendance Sheet", index=False)
                        summary_data.to_excel(writer, sheet_name="Statistical Summary", index=False)
                    
                    excel_data = buffer.getvalue()
                    
                    st.download_button(
                        label="Download Excel Spreadsheet (xlsx)",
                        data=excel_data,
                        file_name=f"{selected_course_id}_attendance_report.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )
                    
                    csv = summary_data.to_csv(index=False).encode('utf-8')
                    st.download_button(
                        label="Download Statistical Summary (CSV)",
                        data=csv,
                        file_name=f"{selected_course_id}_summary.csv",
                        mime="text/csv"
                    )

    # ----------------- Tab: Alert & Notifications (NEW) -----------------
    elif menu == "📧 Alert & Notifications":
        st.title("📧 Warning Alert & Notification Centre")
        st.markdown("Draft and dispatch warning notices via SMTP to students falling below the **75% requirement**.")
        
        # Select Course for Warnings
        courses_df = query_dataframe("SELECT * FROM courses")
        if courses_df.empty:
            st.warning("No courses available to generate email warning alerts.")
        else:
            course_options = {row['course_name']: row['course_id'] for _, row in courses_df.iterrows()}
            selected_course_name = st.selectbox("Generate Warnings for Course", list(course_options.keys()))
            selected_course_id = course_options[selected_course_name]
            
            # Identify students below 75% for this specific course
            at_risk_list = query_dataframe("""
                SELECT s.student_id, s.student_name, s.student_email,
                       SUM(CASE WHEN a.status = 'Present' THEN 1 ELSE 0 END) * 100.0 / COUNT(a.lecture_id) as rate,
                       SUM(CASE WHEN a.status = 'Absent' THEN 1 ELSE 0 END) as absences,
                       COUNT(a.lecture_id) as total_sessions
                FROM students s
                JOIN attendance a ON s.student_id = a.student_id
                JOIN lectures l ON a.lecture_id = l.lecture_id
                WHERE l.course_id = ?
                GROUP BY s.student_id
                HAVING rate < 75.0
            """, (selected_course_id,))
            
            # Setup layout columns
            config_col, run_col = st.columns([1, 2])
            
            with config_col:
                st.subheader("⚙️ SMTP Mail Setup")
                smtp_mode = st.radio(
                    "Delivery Protocol",
                    ["Simulated Sandbox (No Mail Server Needed)", "Real Mail Server (SMTP)"]
                )
                
                mail_config = {"mode": smtp_mode}
                
                if smtp_mode == "Real Mail Server (SMTP)":
                    mail_config["host"] = st.text_input("SMTP Server Host", "smtp.gmail.com")
                    mail_config["port"] = st.number_input("SMTP SSL/TLS Port", value=587)
                    mail_config["sender"] = st.text_input("Sender Institutional Email")
                    mail_config["password"] = st.text_input("App Password / Password", type="password", help="For security, use an App Password generated from your email account (e.g., Google 2-Factor Auth App Passwords).")
                else:
                    mail_config["host"] = ""
                    mail_config["port"] = 587
                    mail_config["sender"] = "noreply@university.edu"
                    mail_config["password"] = ""
                    st.info("ℹ️ **Sandbox Mode Active**: System compiles real custom warning drafts, executes logical routing, and outputs simulated sending records without configuring a live server.")
            
            with run_col:
                st.subheader("📋 Low Attendance Warning Roster")
                if at_risk_list.empty:
                    st.success("🎉 Compliant! All students registered in this course are currently meeting the 75% minimum threshold.")
                else:
                    st.warning(f"⚠️ **{len(at_risk_list)} student profiles** are currently falling below the 75.0% threshold limit.")
                    st.dataframe(at_risk_list, use_container_width=True)
                    
                    st.divider()
                    st.write("### Draft Warning Notifications")
                    
                    # Store selected warnings
                    selected_notifs = []
                    
                    for index, student in at_risk_list.iterrows():
                        with st.expander(f"✉️ Warning Draft: {student['student_name']} ({student['rate']:.1f}%)"):
                            st.write(f"**Recipient Address**: {student['student_email']}")
                            st.write(f"**Logged Absences**: {student['absences']} out of {student['total_sessions']} sessions")
                            
                            # Custom template view
                            st.code(f"""Subject: ⚠️ WARNING: Low Attendance Alert in {selected_course_id}
Dear {student['student_name']},

This is an automated notification regarding your attendance in course {selected_course_id}.

Our records show that your current attendance rate is {student['rate']:.1f}%. 
Under university regulations, you are required to maintain a minimum of 75.0% attendance in order to sit for the final examinations.

You are currently falling below this threshold. Please reach out to your instructor as soon as possible to discuss how to make up for missed classes.

Sincerely,
Academic Administration & Portal Services""")
                            
                            # Checkbox to queue
                            queue_send = st.checkbox(f"Queue Warning for {student['student_name']}", value=True)
                            if queue_send:
                                selected_notifs.append(student)
                                
                    st.divider()
                    
                    # Send execution trigger
                    if st.button("🚀 Dispatch Selected Warnings", type="primary"):
                        if not selected_notifs:
                            st.error("Please queue at least one student notice to continue.")
                        else:
                            success_count = 0
                            failed_count = 0
                            logs_compiled = []
                            
                            # Process warnings
                            for student in selected_notifs:
                                success, log_msg = send_alert_email(
                                    to_email=student['student_email'],
                                    student_name=student['student_name'],
                                    course_id=selected_course_id,
                                    rate=student['rate'],
                                    config=mail_config
                                )
                                if success:
                                    success_count += 1
                                else:
                                    failed_count += 1
                                logs_compiled.append(log_msg)
                                
                            # Success feedback
                            st.success(f"📬 Notifications Processed! Success: {success_count} | Failed: {failed_count}")
                            with st.expander("📝 Transaction Log Detail"):
                                for log in logs_compiled:
                                    st.write(log)

    # ----------------- Tab: Student Directory -----------------
    elif menu == "🧑‍🎓 Student Directory":
        st.title("🧑‍🎓 Student Attendance Profiles")
        st.markdown("Lookup individual academic records, detailed metrics, and specific statuses.")
        
        students_df = query_dataframe("SELECT * FROM students ORDER BY student_name")
        
        if students_df.empty:
            st.warning("No student records available.")
        else:
            student_map = {row['student_name']: row['student_id'] for _, row in students_df.iterrows()}
            selected_student_name = st.selectbox("Search / Select Student Profile", list(student_map.keys()))
            selected_student_id = student_map[selected_student_name]
            
            student_details = students_df[students_df['student_id'] == selected_student_id].iloc[0]
            
            p_col1, p_col2 = st.columns([1, 2])
            with p_col1:
                st.markdown(f"### Profile: **{student_details['student_name']}**")
                st.markdown(f"**ID:** `{student_details['student_id']}`")
                st.markdown(f"**Email:** {student_details['student_email']}")
                
            with p_col2:
                ind_metrics = query_dataframe("""
                    SELECT 
                        SUM(CASE WHEN status = 'Present' THEN 1 ELSE 0 END) as present,
                        SUM(CASE WHEN status = 'Absent' THEN 1 ELSE 0 END) as absent,
                        SUM(CASE WHEN status = 'Excused' THEN 1 ELSE 0 END) as excused,
                        COUNT(*) as total
                    FROM attendance
                    WHERE student_id = ?
                """, (selected_student_id,)).iloc[0]
                
                if ind_metrics['total'] > 0:
                    p_rate = (ind_metrics['present'] / ind_metrics['total']) * 100
                    
                    st.subheader("Performance Indicators")
                    ind_col1, ind_col2, ind_col3 = st.columns(3)
                    ind_col1.metric("Total Sessions Registered", ind_metrics['total'])
                    ind_col2.metric("Total Present Sessions", ind_metrics['present'])
                    
                    if p_rate >= 75.0:
                        ind_col3.metric("Individual Attendance Rate", f"{p_rate:.1f}%", "Good (>=75%)", delta_color="normal")
                    else:
                        ind_col3.metric("Individual Attendance Rate", f"{p_rate:.1f}%", "Below Limit (<75%)", delta_color="inverse")
                else:
                    st.info("This student has not had any attendance records logged yet.")
                    
            st.divider()
            
            st.subheader("Detailed Attendance Timeline")
            breakdown_df = query_dataframe("""
                SELECT l.lecture_date as 'Date', l.course_id as 'Course Code', c.course_name as 'Course Name', 
                       l.lecture_topic as 'Lecture Topic', a.status as 'Marked Status'
                FROM attendance a
                JOIN lectures l ON a.lecture_id = l.lecture_id
                JOIN courses c ON l.course_id = c.course_id
                WHERE a.student_id = ?
                ORDER BY l.lecture_date DESC
            """, (selected_student_id,))
            
            if not breakdown_df.empty:
                st.dataframe(breakdown_df, use_container_width=True)
            else:
                st.write("No lecture records exist for this student.")

    # ----------------- Tab: Manage Roster -----------------
    elif menu == "⚙️ Manage Roster":
        st.title("⚙️ Roster and Course Configuration")
        st.markdown("Add, edit, and configure the core courses and students in the directory.")
        
        tab1, tab2 = st.tabs(["📚 Course Records", "🧑‍🎓 Student Roster"])
        
        with tab1:
            st.subheader("Course Database")
            existing_courses = query_dataframe("SELECT * FROM courses")
            st.dataframe(existing_courses, use_container_width=True)
            
            with st.expander("➕ Register a New Course"):
                c_id = st.text_input("Course Code (e.g., CS101, BIO302)")
                c_name = st.text_input("Course Title (e.g., Intro to Algorithmic Analysis)")
                if st.button("Add Course Record"):
                    if c_id and c_name:
                        success = run_transaction("INSERT INTO courses (course_id, course_name) VALUES (?, ?)", (c_id.strip(), c_name.strip()))
                        if success:
                            st.success(f"Course '{c_name}' successfully added!")
                            st.rerun()
                    else:
                        st.error("Please fill out both Course Code and Title.")
                        
        with tab2:
            st.subheader("Student Database")
            existing_students = query_dataframe("SELECT * FROM students ORDER BY student_id")
            st.dataframe(existing_students, use_container_width=True)
            
            col_add, col_bulk = st.columns(2)
            
            with col_add:
                with st.expander("➕ Register a Single Student"):
                    s_id = st.text_input("Student Registration ID (e.g., S1011)")
                    s_name = st.text_input("Full Name")
                    s_email = st.text_input("Institutional Email")
                    
                    if st.button("Add Student Record"):
                        if s_id and s_name and s_email:
                            success = run_transaction(
                                "INSERT INTO students (student_id, student_name, student_email) VALUES (?, ?, ?)",
                                (s_id.strip(), s_name.strip(), s_email.strip())
                            )
                            if success:
                                st.success(f"Student '{s_name}' registered successfully.")
                                st.rerun()
                        else:
                            st.error("Please fill in all details.")
                            
            with col_bulk:
                with st.expander("📤 Bulk Import Student Directory (CSV)"):
                    st.markdown("Upload a CSV file containing headers: `student_id`, `student_name`, `student_email`.")
                    uploaded_file = st.file_uploader("Choose a CSV file", type="csv")
                    
                    if uploaded_file is not None:
                        try:
                            bulk_df = pd.read_csv(uploaded_file)
                            required_cols = {'student_id', 'student_name', 'student_email'}
                            
                            if not required_cols.issubset(set(bulk_df.columns)):
                                st.error(f"Missing required columns. Your CSV must have columns: {required_cols}")
                            else:
                                conn = get_db_connection()
                                cursor = conn.cursor()
                                success_count = 0
                                error_count = 0
                                
                                for _, row in bulk_df.iterrows():
                                    try:
                                        cursor.execute(
                                            "INSERT INTO students (student_id, student_name, student_email) VALUES (?, ?, ?)",
                                            (str(row['student_id']).strip(), str(row['student_name']).strip(), str(row['student_email']).strip())
                                        )
                                        success_count += 1
                                    except sqlite3.Error:
                                        error_count += 1
                                        
                                conn.commit()
                                conn.close()
                                
                                st.success(f"Bulk registration completed! Successfully registered {success_count} students. (Failed entries due to ID duplication: {error_count})")
                                st.rerun()
                                
                        except Exception as e:
                            st.error(f"Failed to process CSV file: {e}")
