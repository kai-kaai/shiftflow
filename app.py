import os
import sqlite3
import json
import datetime
import copy
from flask import Flask, jsonify, request, render_template
from log_templates import DEFAULT_LOG_TEMPLATES

app = Flask(__name__, template_folder='templates', static_folder='static')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'shiftflow.db')

DEFAULT_EMPLOYEES = [
    'BP', 'CQ', 'DY', 'JZ', 'KJ', 'PB', 'PP', 'PR', 'SG', 'SN', 'TH', 'TT', 'TY', 'WE', 'WF', 'YJ', 'YQ'
]

def get_month_name(month_num):
    months = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
    if 1 <= month_num <= 12:
        return months[month_num - 1]
    return "MAY"

def get_clean_initials(emp_name):
    if not emp_name:
        return ""
    emp_str = str(emp_name).strip().upper()
    if '/' in emp_str:
        parts = emp_str.split('/')
        if parts[0] == '-':
            clean = parts[1]
        else:
            clean = parts[0]
    else:
        clean = emp_str
    return clean.replace('-', '').strip()

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    db_exists = os.path.exists(DB_PATH)
    conn = get_db()
    cursor = conn.cursor()
    
    # 1. Create tables
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            initials TEXT UNIQUE NOT NULL,
            full_name TEXT NOT NULL,
            is_active INTEGER DEFAULT 1,
            queue_order INTEGER NOT NULL
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS shifts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            shift_type TEXT NOT NULL,
            supervisor TEXT NOT NULL,
            queue TEXT NOT NULL,       -- JSON array of initials
            selections TEXT NOT NULL,  -- JSON object of choices
            is_completed INTEGER DEFAULT 0
        )
    ''')
    
    # Add columns if they do not exist
    cursor.execute("PRAGMA table_info(shifts)")
    columns = [row[1] for row in cursor.fetchall()]
    if 'leaves' not in columns:
        cursor.execute("ALTER TABLE shifts ADD COLUMN leaves TEXT DEFAULT '[]'")
    if 'ots' not in columns:
        cursor.execute("ALTER TABLE shifts ADD COLUMN ots TEXT DEFAULT '[]'")
    if 'custom_log' not in columns:
        cursor.execute("ALTER TABLE shifts ADD COLUMN custom_log TEXT DEFAULT '[]'")
        
    # 2. Create template_logs table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS template_logs (
            shift_type TEXT PRIMARY KEY,
            custom_log TEXT DEFAULT '[]',
            layout TEXT DEFAULT '{}'
        )
    ''')

    cursor.execute("PRAGMA table_info(template_logs)")
    template_columns = [row[1] for row in cursor.fetchall()]
    if 'layout' not in template_columns:
        cursor.execute("ALTER TABLE template_logs ADD COLUMN layout TEXT DEFAULT '{}'")

    for shift_type, template_data in DEFAULT_LOG_TEMPLATES.items():
        layout_json = json.dumps(template_data)
        cursor.execute("SELECT layout FROM template_logs WHERE shift_type = ?", (shift_type,))
        template_row = cursor.fetchone()
        if template_row:
            existing_layout = template_row["layout"] or '{}'
            if existing_layout in ('{}', ''):
                cursor.execute(
                    "UPDATE template_logs SET layout = ? WHERE shift_type = ?",
                    (layout_json, shift_type)
                )
        else:
            cursor.execute(
                "INSERT INTO template_logs (shift_type, custom_log, layout) VALUES (?, '[]', ?)",
                (shift_type, layout_json)
            )

    conn.commit()

    cursor.execute("SELECT COUNT(*) FROM employees")
    emp_count = cursor.fetchone()[0]
    if emp_count == 0:
        for idx, emp in enumerate(DEFAULT_EMPLOYEES):
            cursor.execute(
                "INSERT INTO employees (initials, full_name, is_active, queue_order) VALUES (?, ?, 1, ?)",
                (emp, f"Employee {emp}", idx + 1)
            )
        conn.commit()
        print(f"Seeded {len(DEFAULT_EMPLOYEES)} default employees.")

    conn.close()

# Initialize DB on import/startup
init_db()

def get_log_layout(shift_type):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT layout FROM template_logs WHERE shift_type = ?", (shift_type,))
    row = cursor.fetchone()
    conn.close()

    if row and row["layout"]:
        try:
            layout = json.loads(row["layout"])
            if layout.get("hours") and layout.get("rows"):
                return layout
        except json.JSONDecodeError:
            pass

    return copy.deepcopy(DEFAULT_LOG_TEMPLATES.get(shift_type, {"hours": [], "rows": []}))

def parse_custom_log_map(custom_log_val):
    custom_log_data = []
    if custom_log_val:
        try:
            custom_log_data = json.loads(custom_log_val)
        except json.JSONDecodeError:
            custom_log_data = []

    custom_rows_map = {}
    for row_data in custom_log_data:
        slot_val = row_data.get("slot")
        if slot_val:
            custom_rows_map[str(slot_val).strip().upper()] = row_data
    return custom_rows_map

def build_choice_maps(selections, is_morning):
    morning_choice_to_emp = {}
    afternoon_choice_to_emp = {}

    for emp, choice in selections.items():
        ch_norm = str(choice).strip().upper()
        if is_morning:
            if ch_norm.endswith('/-') and ch_norm.startswith('W/S'):
                morning_choice_to_emp[ch_norm[:-2]] = emp
            elif ch_norm.startswith('-/W/S'):
                afternoon_choice_to_emp[ch_norm[2:]] = emp
            else:
                if ch_norm.startswith('M') and ch_norm[1:].isdigit():
                    ch_norm = ch_norm[1:]

                if '/' in ch_norm and not ch_norm.startswith('W/S'):
                    parts = ch_norm.split('/')
                    m_part = parts[0].strip()
                    a_part = parts[1].strip()
                    if m_part.startswith('M') and m_part[1:].isdigit():
                        m_part = m_part[1:]
                    if a_part.startswith('M') and a_part[1:].isdigit():
                        a_part = a_part[1:]
                    if m_part and m_part != '-':
                        morning_choice_to_emp[m_part] = emp
                    if a_part and a_part != '-':
                        afternoon_choice_to_emp[a_part] = emp
                else:
                    morning_choice_to_emp[ch_norm] = emp
                    afternoon_choice_to_emp[ch_norm] = emp
        else:
            morning_choice_to_emp[ch_norm] = emp
            afternoon_choice_to_emp[ch_norm] = emp

    return morning_choice_to_emp, afternoon_choice_to_emp

def resolve_employee_for_slot(slot_str, slot_id, is_morning, morning_choice_to_emp, afternoon_choice_to_emp):
    if is_morning:
        emp_m = morning_choice_to_emp.get(slot_str, "")
        emp_a = afternoon_choice_to_emp.get(slot_str, "")

        clean_m = get_clean_initials(emp_m)
        clean_a = get_clean_initials(emp_a)

        if clean_m and clean_a:
            return clean_m if clean_m == clean_a else f"{clean_m}/{clean_a}"
        return clean_m or clean_a

    if slot_id.startswith('A') and slot_id[1:].isdigit():
        emp = morning_choice_to_emp.get(slot_id, "")
    elif slot_id.startswith('N') and slot_id[1:].isdigit():
        emp = morning_choice_to_emp.get(slot_id, "")
    elif slot_str == "W/S N" and "W/S N" in morning_choice_to_emp:
        emp = morning_choice_to_emp["W/S N"]
    elif slot_str in ["FDO A", "FDO1", "FDO2"] and slot_str in morning_choice_to_emp:
        emp = morning_choice_to_emp[slot_str]
    else:
        emp = ""

    return get_clean_initials(emp) if emp else ""

def apply_custom_row_overrides(row, custom_row, include_employee=True):
    if not custom_row:
        return row

    if include_employee and "employee" in custom_row:
        row["employee"] = custom_row["employee"]
    if "employee_bg" in custom_row:
        row["employee_bg"] = custom_row["employee_bg"]

    custom_cells = custom_row.get("cells", [])
    for idx, cell_data in enumerate(custom_cells):
        if idx < len(row["cells"]):
            if "value" in cell_data:
                row["cells"][idx]["value"] = cell_data["value"]
            if "bg_color" in cell_data:
                row["cells"][idx]["bg_color"] = cell_data["bg_color"]
    return row

def build_hourly_log_rows(layout, is_morning, selections=None, custom_log_val=None, include_employee=True):
    selections = selections or {}
    morning_choice_to_emp, afternoon_choice_to_emp = build_choice_maps(selections, is_morning)
    custom_rows_map = parse_custom_log_map(custom_log_val)

    rows = []
    for base_row in layout["rows"]:
        row = copy.deepcopy(base_row)
        slot_str = row["slot"]
        slot_id = row["slot_id"]

        if include_employee and selections:
            row["employee"] = resolve_employee_for_slot(
                slot_str, slot_id, is_morning, morning_choice_to_emp, afternoon_choice_to_emp
            )
        else:
            row["employee"] = ""

        custom_row = custom_rows_map.get(slot_id.upper())
        apply_custom_row_overrides(row, custom_row, include_employee=include_employee)
        rows.append(row)

    return rows

def resolve_shift_type_slug(shift_type_slug):
    if shift_type_slug == "M8_A14":
        return "M8/A14"
    if shift_type_slug in ["A_N", "A+N"]:
        return "A+N"
    return None

# REST API ENDPOINTS

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/hourly-log/view')
def view_hourly_log_standalone():
    return render_template('hourly_log_view.html')

# 1. Roster APIs
@app.route('/api/employees', methods=['GET'])
def get_employees():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM employees ORDER BY queue_order ASC")
    rows = cursor.fetchall()
    conn.close()
    
    employees = []
    for r in rows:
        employees.append({
            "id": r["id"],
            "initials": r["initials"],
            "full_name": r["full_name"],
            "is_active": r["is_active"],
            "queue_order": r["queue_order"]
        })
    return jsonify({"employees": employees})

@app.route('/api/employees', methods=['POST'])
def save_employee():
    data = request.json
    if not data or 'initials' not in data:
        return jsonify({"error": "Missing initials"}), 400
        
    initials = data.get('initials').strip().upper()
    full_name = data.get('full_name', f"Employee {initials}").strip()
    is_active = data.get('is_active', 1)
    emp_id = data.get('id')

    conn = get_db()
    cursor = conn.cursor()
    try:
        if emp_id:
            # Update existing
            cursor.execute(
                "UPDATE employees SET initials = ?, full_name = ?, is_active = ? WHERE id = ?",
                (initials, full_name, is_active, emp_id)
            )
        else:
            # Get max queue order
            cursor.execute("SELECT MAX(queue_order) FROM employees")
            max_order = cursor.fetchone()[0] or 0
            # Insert new
            cursor.execute(
                "INSERT INTO employees (initials, full_name, is_active, queue_order) VALUES (?, ?, ?, ?)",
                (initials, full_name, is_active, max_order + 1)
            )
        conn.commit()
        return jsonify({"success": True})
    except sqlite3.IntegrityError:
        return jsonify({"error": f"ชื่อย่อพนักงาน '{initials}' ซ้ำในระบบ"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@app.route('/api/employees/<int:id>', methods=['DELETE'])
def delete_employee(id):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM employees WHERE id = ?", (id,))
        conn.commit()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

# 2. Shifts CRUD APIs
@app.route('/api/shifts', methods=['GET'])
def get_shifts():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM shifts ORDER BY date DESC, id DESC")
    rows = cursor.fetchall()
    conn.close()
    
    shifts = []
    for r in rows:
        parsed_date = datetime.datetime.strptime(r["date"], '%Y-%m-%d')
        day = parsed_date.day
        month = get_month_name(parsed_date.month)
        year = parsed_date.year
        date_display = f"{day} {month} {year}"

        # Safely parse leaves and ots
        leaves_val = r["leaves"] if "leaves" in r.keys() else "[]"
        ots_val = r["ots"] if "ots" in r.keys() else "[]"
        try:
            leaves = json.loads(leaves_val) if leaves_val else []
        except:
            leaves = []
        try:
            ots = json.loads(ots_val) if ots_val else []
        except:
            ots = []

        shifts.append({
            "id": r["id"],
            "date": r["date"],
            "date_display": date_display,
            "shift_type": r["shift_type"],
            "supervisor": r["supervisor"],
            "queue": json.loads(r["queue"]),
            "selections": json.loads(r["selections"]),
            "leaves": leaves,
            "ots": ots,
            "is_completed": r["is_completed"]
        })
    return jsonify({"shifts": shifts})

@app.route('/api/shifts', methods=['POST'])
def create_shift():
    data = request.json
    if not data or 'date' not in data or 'shift_type' not in data:
        return jsonify({"error": "Missing date or shift_type"}), 400
        
    date_str = data.get('date') # YYYY-MM-DD
    shift_type = data.get('shift_type')
    supervisor = data.get('supervisor', '').strip()
    custom_queue = data.get('queue') # optional custom queue

    conn = get_db()
    cursor = conn.cursor()
    
    try:
        if custom_queue:
            queue_list = custom_queue
        else:
            # 1. Fetch active employees sorted by roster order
            cursor.execute("SELECT initials FROM employees WHERE is_active = 1 ORDER BY queue_order ASC")
            active_emps = [row["initials"] for row in cursor.fetchall()]
            
            if not active_emps:
                return jsonify({"error": "ไม่มีรายชื่อพนักงานที่เปิดใช้งาน (Active) ในระบบ โปรดเพิ่มหรือเปิดใช้งานรายชื่อก่อน"}), 400

            # 2. Find the last shift queue to compute rotating order
            cursor.execute("SELECT queue FROM shifts ORDER BY date DESC, id DESC LIMIT 1")
            last_shift_row = cursor.fetchone()
            
            if last_shift_row:
                last_queue = json.loads(last_shift_row["queue"])
                
                # Rotate last queue by shifting left by 1
                if last_queue:
                    first = last_queue.pop(0)
                    last_queue.append(first)
                
                # Filter to keep only currently active employees
                queue_list = [emp for emp in last_queue if emp in active_emps]
                
                # Append active employees not already in the queue (e.g. newly activated)
                for emp in active_emps:
                    if emp not in queue_list:
                        queue_list.append(emp)
            else:
                # Fallback to default active roster order
                queue_list = active_emps

        # Fetch template custom_log if exists
        cursor.execute("SELECT custom_log FROM template_logs WHERE shift_type = ?", (shift_type,))
        template_row = cursor.fetchone()
        custom_log_val = template_row["custom_log"] if template_row else '[]'

        cursor.execute(
            '''INSERT INTO shifts (date, shift_type, supervisor, queue, selections, is_completed, custom_log) 
               VALUES (?, ?, ?, ?, '{}', 0, ?)''',
            (date_str, shift_type, supervisor, json.dumps(queue_list), custom_log_val)
        )
        conn.commit()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@app.route('/api/shifts/<int:id>', methods=['DELETE'])
def delete_shift(id):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM shifts WHERE id = ?", (id,))
        conn.commit()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

# 3. Shift Selections Saving
@app.route('/api/shifts/<int:id>', methods=['POST'])
def save_shift_selections(id):
    data = request.json
    if not data or 'selections' not in data:
        return jsonify({"error": "Missing selections"}), 400
        
    selections = data.get('selections')
    is_completed = data.get('is_completed', 1)
    leaves = data.get('leaves', [])
    ots = data.get('ots', [])

    conn = get_db()
    cursor = conn.cursor()
    try:
        # Check if table has leaves and ots columns
        cursor.execute("PRAGMA table_info(shifts)")
        columns = [row[1] for row in cursor.fetchall()]
        if 'leaves' in columns and 'ots' in columns:
            cursor.execute(
                "UPDATE shifts SET selections = ?, is_completed = ?, leaves = ?, ots = ? WHERE id = ?",
                (json.dumps(selections), is_completed, json.dumps(leaves), json.dumps(ots), id)
            )
        else:
            cursor.execute(
                "UPDATE shifts SET selections = ?, is_completed = ? WHERE id = ?",
                (json.dumps(selections), is_completed, id)
            )
        conn.commit()
        return jsonify({"success": True, "message": "บันทึกผลการจัดเวรพนักงานลงฐานข้อมูลเรียบร้อยแล้ว"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
@app.route('/api/shifts/<int:id>/hourly-log', methods=['GET'])
def get_shift_hourly_log(id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM shifts WHERE id = ?", (id,))
    shift = cursor.fetchone()
    conn.close()

    if not shift:
        return jsonify({"error": "Shift not found"}), 404

    try:
        is_morning = shift["shift_type"] == 'M8/A14'
        layout = get_log_layout(shift["shift_type"])
        selections = json.loads(shift["selections"])
        custom_log_val = shift["custom_log"] if "custom_log" in shift.keys() else "[]"

        rows = build_hourly_log_rows(
            layout,
            is_morning=is_morning,
            selections=selections,
            custom_log_val=custom_log_val,
            include_employee=True
        )

        parsed_date = datetime.datetime.strptime(shift["date"], '%Y-%m-%d')
        date_display = f"{parsed_date.day} {get_month_name(parsed_date.month)} {parsed_date.year}"

        return jsonify({
            "shift_id": shift["id"],
            "date_display": date_display,
            "shift_type": shift["shift_type"],
            "supervisor": shift["supervisor"],
            "hours": layout["hours"],
            "rows": rows
        })
    except Exception as e:
        return jsonify({"error": f"Failed to load template layout: {str(e)}"}), 500
@app.route('/api/shifts/<int:id>/hourly-log', methods=['POST'])
def save_shift_hourly_log(id):
    data = request.json
    if not data or 'custom_log' not in data:
        return jsonify({"error": "Missing custom_log"}), 400
        
    custom_log = data.get('custom_log')

    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE shifts SET custom_log = ? WHERE id = ?",
            (json.dumps(custom_log), id)
        )
        conn.commit()
        return jsonify({"success": True, "message": "บันทึกข้อมูลตาราง Log เรียบร้อยแล้ว"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@app.route('/api/templates/<shift_type_slug>/hourly-log', methods=['GET'])
def get_template_hourly_log(shift_type_slug):
    shift_type = resolve_shift_type_slug(shift_type_slug)
    if not shift_type:
        return jsonify({"error": "Invalid shift type"}), 400

    try:
        is_morning = shift_type == 'M8/A14'
        layout = get_log_layout(shift_type)

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT custom_log FROM template_logs WHERE shift_type = ?", (shift_type,))
        template_row = cursor.fetchone()
        conn.close()

        custom_log_val = template_row["custom_log"] if template_row else "[]"
        rows = build_hourly_log_rows(
            layout,
            is_morning=is_morning,
            custom_log_val=custom_log_val,
            include_employee=False
        )

        date_display = "Morning Master Log" if is_morning else "Afternoon/Night Master Log"

        return jsonify({
            "shift_id": f"template:{shift_type}",
            "date_display": date_display,
            "shift_type": shift_type,
            "supervisor": "",
            "hours": layout["hours"],
            "rows": rows
        })
    except Exception as e:
        return jsonify({"error": f"Failed to load template layout: {str(e)}"}), 500

@app.route('/api/templates/<shift_type_slug>/hourly-log', methods=['POST'])
def save_template_hourly_log(shift_type_slug):
    shift_type = resolve_shift_type_slug(shift_type_slug)
    if not shift_type:
        return jsonify({"error": "Invalid shift type"}), 400
    data = request.json
    if not data or 'custom_log' not in data:
        return jsonify({"error": "Missing custom_log"}), 400
        
    custom_log = data.get('custom_log')

    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT 1 FROM template_logs WHERE shift_type = ?", (shift_type,))
        exists = cursor.fetchone()
        if exists:
            cursor.execute(
                "UPDATE template_logs SET custom_log = ? WHERE shift_type = ?",
                (json.dumps(custom_log), shift_type)
            )
        else:
            cursor.execute(
                "INSERT INTO template_logs (shift_type, custom_log) VALUES (?, ?)",
                (shift_type, json.dumps(custom_log))
            )
        conn.commit()
        return jsonify({"success": True, "message": "บันทึกข้อมูล Master Log เรียบร้อยแล้ว"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=True)
