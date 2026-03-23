from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import sqlite3
import os
from datetime import date

app = Flask(__name__)
app.secret_key = "attendance-secret-key-change-this"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(BASE_DIR, "students.db")


def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('admin', 'teacher', 'student'))
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS classes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            class_name TEXT UNIQUE NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS teacher_classes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            teacher_user_id INTEGER NOT NULL,
            class_id INTEGER NOT NULL,
            UNIQUE(teacher_user_id, class_id),
            FOREIGN KEY(teacher_user_id) REFERENCES users(id),
            FOREIGN KEY(class_id) REFERENCES classes(id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            roll_no TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            class_id INTEGER NOT NULL,
            user_id INTEGER UNIQUE,
            FOREIGN KEY(class_id) REFERENCES classes(id),
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            att_date TEXT NOT NULL,
            hour_no INTEGER NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('Present', 'Absent')),
            UNIQUE(student_id, att_date, hour_no),
            FOREIGN KEY(student_id) REFERENCES students(id)
        )
    """)

    admin = cur.execute(
        "SELECT id FROM users WHERE username = ?",
        ("admin",)
    ).fetchone()

    if not admin:
        cur.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
            ("admin", generate_password_hash("admin123"), "admin")
        )

    conn.commit()
    conn.close()


init_db()


def login_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return func(*args, **kwargs)
    return wrapper


def role_required(*roles):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if session.get("role") not in roles:
                flash("You are not allowed to access that page.")
                return redirect(url_for("login"))
            return func(*args, **kwargs)
        return wrapper
    return decorator


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        conn = get_db()
        user = conn.execute(
            "SELECT * FROM users WHERE username = ?",
            (username,)
        ).fetchone()
        conn.close()

        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["role"] = user["role"]

            if user["role"] == "admin":
                return redirect(url_for("admin_dashboard"))
            if user["role"] == "teacher":
                return redirect(url_for("teacher_attendance"))
            return redirect(url_for("records"))

        flash("Invalid username or password.")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
def home():
    if "user_id" not in session:
        return redirect(url_for("login"))

    if session["role"] == "admin":
        return redirect(url_for("admin_dashboard"))
    if session["role"] == "teacher":
        return redirect(url_for("teacher_attendance"))
    return redirect(url_for("records"))


@app.route("/admin", methods=["GET"])
@login_required
@role_required("admin")
def admin_dashboard():
    conn = get_db()

    teachers = conn.execute("""
        SELECT id, username
        FROM users
        WHERE role = 'teacher'
        ORDER BY username
    """).fetchall()

    classes = conn.execute("""
        SELECT id, class_name
        FROM classes
        ORDER BY class_name
    """).fetchall()

    students = conn.execute("""
        SELECT s.id, s.roll_no, s.name, c.class_name, u.username
        FROM students s
        JOIN classes c ON s.class_id = c.id
        LEFT JOIN users u ON s.user_id = u.id
        ORDER BY c.class_name, s.roll_no
    """).fetchall()

    assignments = conn.execute("""
        SELECT tc.id, u.username AS teacher_name, c.class_name
        FROM teacher_classes tc
        JOIN users u ON tc.teacher_user_id = u.id
        JOIN classes c ON tc.class_id = c.id
        ORDER BY u.username, c.class_name
    """).fetchall()

    conn.close()

    return render_template(
        "admin_dashboard.html",
        teachers=teachers,
        classes=classes,
        students=students,
        assignments=assignments,
        current_user=session.get("username"),
        role=session.get("role")
    )


@app.route("/admin/add-class", methods=["POST"])
@login_required
@role_required("admin")
def add_class():
    class_name = request.form.get("class_name", "").strip()

    if not class_name:
        flash("Class name is required.")
        return redirect(url_for("admin_dashboard"))

    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO classes (class_name) VALUES (?)",
            (class_name,)
        )
        conn.commit()
        flash("Class added successfully.")
    except sqlite3.IntegrityError:
        flash("Class already exists.")
    finally:
        conn.close()

    return redirect(url_for("admin_dashboard"))


@app.route("/admin/add-teacher", methods=["POST"])
@login_required
@role_required("admin")
def add_teacher():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "").strip()

    if not username or not password:
        flash("Teacher username and password are required.")
        return redirect(url_for("admin_dashboard"))

    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
            (username, generate_password_hash(password), "teacher")
        )
        conn.commit()
        flash("Teacher added successfully.")
    except sqlite3.IntegrityError:
        flash("Teacher username already exists.")
    finally:
        conn.close()

    return redirect(url_for("admin_dashboard"))


@app.route("/admin/add-student", methods=["POST"])
@login_required
@role_required("admin")
def add_student():
    roll_no = request.form.get("roll_no", "").strip()
    name = request.form.get("name", "").strip()
    class_id = request.form.get("class_id", "").strip()
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "").strip()

    if not roll_no or not name or not class_id or not username or not password:
        flash("All student fields are required.")
        return redirect(url_for("admin_dashboard"))

    conn = get_db()
    try:
        cur = conn.cursor()

        cur.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
            (username, generate_password_hash(password), "student")
        )
        user_id = cur.lastrowid

        cur.execute(
            "INSERT INTO students (roll_no, name, class_id, user_id) VALUES (?, ?, ?, ?)",
            (roll_no, name, int(class_id), user_id)
        )

        conn.commit()
        flash("Student added successfully.")
    except sqlite3.IntegrityError:
        flash("Student roll number or username already exists.")
    finally:
        conn.close()

    return redirect(url_for("admin_dashboard"))


@app.route("/admin/assign-teacher", methods=["POST"])
@login_required
@role_required("admin")
def assign_teacher():
    teacher_user_id = request.form.get("teacher_user_id", "").strip()
    class_id = request.form.get("class_id", "").strip()

    if not teacher_user_id or not class_id:
        flash("Teacher and class are required.")
        return redirect(url_for("admin_dashboard"))

    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO teacher_classes (teacher_user_id, class_id) VALUES (?, ?)",
            (int(teacher_user_id), int(class_id))
        )
        conn.commit()
        flash("Teacher assigned to class.")
    except sqlite3.IntegrityError:
        flash("This teacher is already assigned to that class.")
    finally:
        conn.close()

    return redirect(url_for("admin_dashboard"))


@app.route("/teacher", methods=["GET"])
@login_required
@role_required("teacher")
def teacher_attendance():
    selected_date = request.args.get("date", date.today().isoformat())
    selected_class_id = request.args.get("class_id", type=int)

    conn = get_db()

    classes = conn.execute("""
        SELECT c.id, c.class_name
        FROM teacher_classes tc
        JOIN classes c ON tc.class_id = c.id
        WHERE tc.teacher_user_id = ?
        ORDER BY c.class_name
    """, (session["user_id"],)).fetchall()

    if selected_class_id is None and classes:
        selected_class_id = classes[0]["id"]

    students = []
    attendance_map = {}

    if selected_class_id:
        students = conn.execute("""
            SELECT id, roll_no, name
            FROM students
            WHERE class_id = ?
            ORDER BY roll_no, name
        """, (selected_class_id,)).fetchall()

        rows = conn.execute("""
            SELECT student_id, hour_no, status
            FROM attendance
            WHERE att_date = ?
              AND student_id IN (
                  SELECT id FROM students WHERE class_id = ?
              )
        """, (selected_date, selected_class_id)).fetchall()

        for row in rows:
            attendance_map[(row["student_id"], row["hour_no"])] = row["status"]

    conn.close()

    return render_template(
        "teacher_attendance.html",
        classes=classes,
        students=students,
        selected_class_id=selected_class_id,
        selected_date=selected_date,
        attendance_map=attendance_map,
        current_user=session.get("username"),
        role=session.get("role")
    )


@app.route("/mark-attendance", methods=["POST"])
@login_required
@role_required("teacher")
def mark_attendance():
    data = request.get_json(force=True)

    student_id = int(data["student_id"])
    att_date = data["att_date"]
    hour_no = int(data["hour_no"])
    status = data["status"]

    if status not in ("Present", "Absent"):
        return jsonify({"ok": False, "error": "Invalid status"}), 400

    conn = get_db()

    allowed = conn.execute("""
        SELECT 1
        FROM teacher_classes tc
        JOIN students s ON s.class_id = tc.class_id
        WHERE tc.teacher_user_id = ?
          AND s.id = ?
    """, (session["user_id"], student_id)).fetchone()

    if not allowed:
        conn.close()
        return jsonify({"ok": False, "error": "Not allowed"}), 403

    conn.execute("""
        INSERT INTO attendance (student_id, att_date, hour_no, status)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(student_id, att_date, hour_no)
        DO UPDATE SET status = excluded.status
    """, (student_id, att_date, hour_no, status))
    conn.commit()
    conn.close()

    return jsonify({"ok": True, "status": status})


@app.route("/records")
@login_required
@role_required("admin", "teacher", "student")
def records():
    conn = get_db()
    role = session.get("role")
    selected_student = None
    recent_rows = []
    students = []

    if role == "admin":
        selected_student_id = request.args.get("student_id", type=int)

        students = conn.execute("""
            SELECT
                s.id,
                s.roll_no,
                s.name,
                c.class_name,
                COALESCE(SUM(CASE WHEN a.status = 'Present' THEN 1 ELSE 0 END), 0) AS present_count,
                COALESCE(SUM(CASE WHEN a.status = 'Absent' THEN 1 ELSE 0 END), 0) AS absent_count,
                COUNT(a.id) AS total_count
            FROM students s
            JOIN classes c ON s.class_id = c.id
            LEFT JOIN attendance a ON a.student_id = s.id
            GROUP BY s.id, s.roll_no, s.name, c.class_name
            ORDER BY c.class_name, s.roll_no
        """).fetchall()

        if selected_student_id is None and students:
            selected_student_id = students[0]["id"]

        if selected_student_id is not None:
            selected_student = conn.execute("""
                SELECT
                    s.id,
                    s.roll_no,
                    s.name,
                    c.class_name,
                    COALESCE(SUM(CASE WHEN a.status = 'Present' THEN 1 ELSE 0 END), 0) AS present_count,
                    COALESCE(SUM(CASE WHEN a.status = 'Absent' THEN 1 ELSE 0 END), 0) AS absent_count,
                    COUNT(a.id) AS total_count
                FROM students s
                JOIN classes c ON s.class_id = c.id
                LEFT JOIN attendance a ON a.student_id = s.id
                WHERE s.id = ?
                GROUP BY s.id, s.roll_no, s.name, c.class_name
            """, (selected_student_id,)).fetchone()

    elif role == "teacher":
        selected_student_id = request.args.get("student_id", type=int)

        students = conn.execute("""
            SELECT
                s.id,
                s.roll_no,
                s.name,
                c.class_name,
                COALESCE(SUM(CASE WHEN a.status = 'Present' THEN 1 ELSE 0 END), 0) AS present_count,
                COALESCE(SUM(CASE WHEN a.status = 'Absent' THEN 1 ELSE 0 END), 0) AS absent_count,
                COUNT(a.id) AS total_count
            FROM students s
            JOIN classes c ON s.class_id = c.id
            JOIN teacher_classes tc ON tc.class_id = c.id
            LEFT JOIN attendance a ON a.student_id = s.id
            WHERE tc.teacher_user_id = ?
            GROUP BY s.id, s.roll_no, s.name, c.class_name
            ORDER BY c.class_name, s.roll_no
        """, (session["user_id"],)).fetchall()

        if selected_student_id is None and students:
            selected_student_id = students[0]["id"]

        if selected_student_id is not None:
            selected_student = conn.execute("""
                SELECT
                    s.id,
                    s.roll_no,
                    s.name,
                    c.class_name,
                    COALESCE(SUM(CASE WHEN a.status = 'Present' THEN 1 ELSE 0 END), 0) AS present_count,
                    COALESCE(SUM(CASE WHEN a.status = 'Absent' THEN 1 ELSE 0 END), 0) AS absent_count,
                    COUNT(a.id) AS total_count
                FROM students s
                JOIN classes c ON s.class_id = c.id
                JOIN teacher_classes tc ON tc.class_id = c.id
                LEFT JOIN attendance a ON a.student_id = s.id
                WHERE tc.teacher_user_id = ?
                  AND s.id = ?
                GROUP BY s.id, s.roll_no, s.name, c.class_name
            """, (session["user_id"], selected_student_id)).fetchone()

    else:
        selected_student = conn.execute("""
            SELECT
                s.id,
                s.roll_no,
                s.name,
                c.class_name,
                COALESCE(SUM(CASE WHEN a.status = 'Present' THEN 1 ELSE 0 END), 0) AS present_count,
                COALESCE(SUM(CASE WHEN a.status = 'Absent' THEN 1 ELSE 0 END), 0) AS absent_count,
                COUNT(a.id) AS total_count
            FROM students s
            JOIN classes c ON s.class_id = c.id
            LEFT JOIN attendance a ON a.student_id = s.id
            WHERE s.user_id = ?
            GROUP BY s.id, s.roll_no, s.name, c.class_name
        """, (session["user_id"],)).fetchone()

        students = [selected_student] if selected_student else []

    if selected_student:
        recent_rows = conn.execute("""
            SELECT att_date, hour_no, status
            FROM attendance
            WHERE student_id = ?
            ORDER BY att_date DESC, hour_no ASC
            LIMIT 40
        """, (selected_student["id"],)).fetchall()

    conn.close()

    percentage = 0
    if selected_student and selected_student["total_count"] > 0:
        percentage = round(
            (selected_student["present_count"] / selected_student["total_count"]) * 100
        )

    return render_template(
        "records.html",
        students=students,
        selected_student=selected_student,
        recent_rows=recent_rows,
        percentage=percentage,
        current_user=session.get("username"),
        role=role
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)