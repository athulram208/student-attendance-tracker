from flask import Flask, render_template, request, redirect, url_for, jsonify
import sqlite3
from datetime import date

app = Flask(__name__)
DB_NAME = "students.db"


def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            roll_no TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL
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

    conn.commit()
    conn.close()


init_db()


@app.route("/")
def index():
    selected_date = request.args.get("date", date.today().isoformat())

    conn = get_db()
    students = conn.execute(
        "SELECT id, roll_no, name FROM students ORDER BY roll_no, name"
    ).fetchall()

    rows = conn.execute("""
        SELECT student_id, hour_no, status
        FROM attendance
        WHERE att_date = ?
    """, (selected_date,)).fetchall()
    conn.close()

    attendance_map = {}
    for row in rows:
        attendance_map[(row["student_id"], row["hour_no"])] = row["status"]

    return render_template(
        "index.html",
        students=students,
        selected_date=selected_date,
        attendance_map=attendance_map
    )


@app.route("/add-student", methods=["POST"])
def add_student():
    roll_no = request.form.get("roll_no", "").strip()
    name = request.form.get("name", "").strip()

    if not roll_no or not name:
        return redirect(url_for("index"))

    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO students (roll_no, name) VALUES (?, ?)",
            (roll_no, name)
        )
        conn.commit()
    except sqlite3.IntegrityError:
        pass
    finally:
        conn.close()

    return redirect(url_for("index"))


@app.route("/mark-attendance", methods=["POST"])
def mark_attendance():
    data = request.get_json(force=True)

    student_id = int(data["student_id"])
    att_date = data["att_date"]
    hour_no = int(data["hour_no"])
    status = data["status"]

    if status not in ("Present", "Absent"):
        return jsonify({"ok": False, "error": "Invalid status"}), 400

    conn = get_db()
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
def records():
    selected_student_id = request.args.get("student_id", type=int)

    conn = get_db()

    students = conn.execute("""
        SELECT
            s.id,
            s.roll_no,
            s.name,
            COALESCE(SUM(CASE WHEN a.status = 'Present' THEN 1 ELSE 0 END), 0) AS present_count,
            COALESCE(SUM(CASE WHEN a.status = 'Absent' THEN 1 ELSE 0 END), 0) AS absent_count,
            COUNT(a.id) AS total_count
        FROM students s
        LEFT JOIN attendance a ON a.student_id = s.id
        GROUP BY s.id, s.roll_no, s.name
        ORDER BY s.roll_no, s.name
    """).fetchall()

    if selected_student_id is None and students:
        selected_student_id = students[0]["id"]

    selected_student = None
    recent_rows = []

    if selected_student_id is not None:
        selected_student = conn.execute("""
            SELECT
                s.id,
                s.roll_no,
                s.name,
                COALESCE(SUM(CASE WHEN a.status = 'Present' THEN 1 ELSE 0 END), 0) AS present_count,
                COALESCE(SUM(CASE WHEN a.status = 'Absent' THEN 1 ELSE 0 END), 0) AS absent_count,
                COUNT(a.id) AS total_count
            FROM students s
            LEFT JOIN attendance a ON a.student_id = s.id
            WHERE s.id = ?
            GROUP BY s.id, s.roll_no, s.name
        """, (selected_student_id,)).fetchone()

        recent_rows = conn.execute("""
            SELECT att_date, hour_no, status
            FROM attendance
            WHERE student_id = ?
            ORDER BY att_date DESC, hour_no ASC
            LIMIT 40
        """, (selected_student_id,)).fetchall()

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
        percentage=percentage
    )


if __name__ == "__main__":
    app.run(debug=True)