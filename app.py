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
MASTER_LOG_EDIT_PASSWORD = 'admin'
QUEUE_WORKING_LIMIT = 13

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
    if 'ot_replacements' not in columns:
        cursor.execute("ALTER TABLE shifts ADD COLUMN ot_replacements TEXT DEFAULT '{}'")
        
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

    # Team month queue plans (ห้องจัดคิว)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS team_month_queues (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            team_id TEXT NOT NULL,
            year_month TEXT NOT NULL,
            columns_json TEXT NOT NULL DEFAULT '[]',
            updated_at TEXT,
            UNIQUE(team_id, year_month)
        )
    ''')

    cursor.execute("PRAGMA table_info(team_month_queues)")
    queue_plan_columns = [row[1] for row in cursor.fetchall()]
    if 'roster_json' not in queue_plan_columns:
        cursor.execute("ALTER TABLE team_month_queues ADD COLUMN roster_json TEXT")

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

def ensure_employees_exist(initials_list):
    """Auto-insert any new employee initials from a queue list (used when creating shifts via the form)."""
    if not initials_list:
        return
    conn = get_db()
    cursor = conn.cursor()
    try:
        for raw_ini in initials_list:
            ini = str(raw_ini).strip().upper()
            if not ini:
                continue
            cursor.execute("SELECT 1 FROM employees WHERE initials = ?", (ini,))
            if cursor.fetchone():
                continue
            # Insert new employee at the end of queue order
            cursor.execute("SELECT MAX(queue_order) FROM employees")
            max_order = cursor.fetchone()[0] or 0
            cursor.execute(
                "INSERT INTO employees (initials, full_name, is_active, queue_order) VALUES (?, ?, 1, ?)",
                (ini, f"Employee {ini}", max_order + 1)
            )
        conn.commit()
    finally:
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

@app.route('/queue-room/view')
def view_queue_room_standalone():
    return render_template('queue_room_view.html')

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

# Note: Employee management (add/edit/delete) is no longer exposed via dedicated UI.
# New employees are automatically added when users enter new initials in the
# "ลำดับคิวพนักงาน" field when creating a new shift.

# 1b. Team month queue plans (ห้องจัดคิว)
def _normalize_queue_columns(raw_columns):
    """Normalize columns payload: list of {date, shift_type, queue, supervisor}."""
    if not isinstance(raw_columns, list):
        return []
    normalized = []
    for col in raw_columns:
        if not isinstance(col, dict):
            continue
        date_str = str(col.get('date', '')).strip()
        shift_type = str(col.get('shift_type', '')).strip()
        if not date_str or not shift_type:
            continue
        raw_queue = col.get('queue') or []
        if isinstance(raw_queue, str):
            raw_queue = [line.strip() for line in raw_queue.splitlines()]
        queue_list = [str(q).strip().upper() for q in raw_queue if str(q).strip()]
        supervisor = str(col.get('supervisor', '') or '').strip()
        normalized.append({
            "date": date_str,
            "shift_type": shift_type,
            "queue": queue_list,
            "supervisor": supervisor
        })
    return normalized


def _normalize_roster(raw_roster):
    """Normalize roster payload to [{initials, working}]. Rejects more than 13 working."""
    if raw_roster is None:
        return [], None
    if not isinstance(raw_roster, list):
        return None, "roster ต้องเป็นรายการ"
    seen = set()
    normalized = []
    working_count = 0
    for item in raw_roster:
        if isinstance(item, str):
            initials = item.strip().upper()
            working = False
        elif isinstance(item, dict):
            initials = str(item.get("initials") or "").strip().upper()
            working = bool(item.get("working"))
        else:
            continue
        if not initials or initials in seen:
            continue
        seen.add(initials)
        if working:
            working_count += 1
            if working_count > QUEUE_WORKING_LIMIT:
                return None, f"เลือกคนทำงานได้สูงสุด {QUEUE_WORKING_LIMIT} คน"
        normalized.append({"initials": initials, "working": working})
    return normalized, None


def _parse_saved_roster(raw_json):
    """Return list if roster was saved, or None if this month has no roster yet."""
    if raw_json is None or raw_json == "":
        return None
    try:
        data = json.loads(raw_json)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(data, list):
        return None
    roster, err = _normalize_roster(data)
    if err:
        return None
    return roster


def _row_saved_roster(row):
    if row is None:
        return None
    try:
        keys = row.keys()
    except Exception:
        return None
    if "roster_json" not in keys:
        return None
    return _parse_saved_roster(row["roster_json"])


def _columns_from_row(row):
    try:
        columns = json.loads(row["columns_json"] or "[]")
    except (TypeError, json.JSONDecodeError):
        columns = []
    return columns if isinstance(columns, list) else []


def _find_previous_roster(cursor, team_id, year_month):
    cursor.execute(
        '''SELECT year_month, roster_json FROM team_month_queues
           WHERE team_id = ? AND year_month < ?
             AND roster_json IS NOT NULL AND roster_json != ''
           ORDER BY year_month DESC''',
        (team_id, year_month)
    )
    for prev in cursor.fetchall():
        roster = _parse_saved_roster(prev["roster_json"])
        if roster is None:
            continue
        return roster, prev["year_month"]
    return [], None


def _roster_for_get(cursor, team_id, year_month, row):
    saved = _row_saved_roster(row)
    if saved is not None:
        return saved, None
    return _find_previous_roster(cursor, team_id, year_month)


@app.route('/api/team-month-queues', methods=['GET'])
def get_team_month_queues():
    team_id = (request.args.get('team_id') or '').strip()
    year_month = (request.args.get('year_month') or '').strip()

    conn = get_db()
    cursor = conn.cursor()
    try:
        if team_id and year_month:
            cursor.execute(
                "SELECT * FROM team_month_queues WHERE team_id = ? AND year_month = ?",
                (team_id, year_month)
            )
            row = cursor.fetchone()
            roster, copied_from = _roster_for_get(cursor, team_id, year_month, row)
            if not row:
                return jsonify({
                    "team_id": team_id,
                    "year_month": year_month,
                    "columns": [],
                    "roster": roster,
                    "roster_copied_from": copied_from,
                    "updated_at": None
                })
            return jsonify({
                "team_id": row["team_id"],
                "year_month": row["year_month"],
                "columns": _columns_from_row(row),
                "roster": roster,
                "roster_copied_from": copied_from,
                "updated_at": row["updated_at"]
            })

        # Optional: all teams for a month, or all plans
        if year_month:
            cursor.execute(
                "SELECT * FROM team_month_queues WHERE year_month = ? ORDER BY team_id ASC",
                (year_month,)
            )
        else:
            cursor.execute("SELECT * FROM team_month_queues ORDER BY year_month DESC, team_id ASC")

        plans = []
        for row in cursor.fetchall():
            saved_roster = _row_saved_roster(row)
            plans.append({
                "team_id": row["team_id"],
                "year_month": row["year_month"],
                "columns": _columns_from_row(row),
                "roster": saved_roster if saved_roster is not None else [],
                "updated_at": row["updated_at"]
            })
        return jsonify({"plans": plans})
    finally:
        conn.close()


@app.route('/api/team-month-queues', methods=['PUT'])
def put_team_month_queues():
    data = request.json or {}
    team_id = str(data.get('team_id', '')).strip()
    year_month = str(data.get('year_month', '')).strip()
    raw_columns = data.get('columns')

    if not team_id or not year_month:
        return jsonify({"error": "ต้องระบุ team_id และ year_month"}), 400
    if len(year_month) != 7 or year_month[4] != '-':
        return jsonify({"error": "year_month ต้องเป็นรูปแบบ YYYY-MM"}), 400

    columns = _normalize_queue_columns(raw_columns)
    roster_provided = 'roster' in data
    roster = None
    if roster_provided:
        roster, roster_error = _normalize_roster(data.get('roster'))
        if roster_error:
            return jsonify({"error": roster_error}), 400

    all_initials = []
    for col in columns:
        all_initials.extend(col["queue"])
    if roster:
        all_initials.extend(item["initials"] for item in roster)
    ensure_employees_exist(all_initials)

    updated_at = datetime.datetime.now().isoformat(timespec='seconds')
    conn = get_db()
    cursor = conn.cursor()
    try:
        if roster_provided:
            cursor.execute(
                '''INSERT INTO team_month_queues (team_id, year_month, columns_json, roster_json, updated_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(team_id, year_month) DO UPDATE SET
                     columns_json = excluded.columns_json,
                     roster_json = excluded.roster_json,
                     updated_at = excluded.updated_at''',
                (
                    team_id,
                    year_month,
                    json.dumps(columns, ensure_ascii=False),
                    json.dumps(roster, ensure_ascii=False),
                    updated_at
                )
            )
        else:
            cursor.execute(
                '''INSERT INTO team_month_queues (team_id, year_month, columns_json, updated_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(team_id, year_month) DO UPDATE SET
                     columns_json = excluded.columns_json,
                     updated_at = excluded.updated_at''',
                (team_id, year_month, json.dumps(columns, ensure_ascii=False), updated_at)
            )
            cursor.execute(
                "SELECT roster_json FROM team_month_queues WHERE team_id = ? AND year_month = ?",
                (team_id, year_month)
            )
            saved_row = cursor.fetchone()
            roster = _parse_saved_roster(saved_row["roster_json"]) if saved_row else None
            if roster is None:
                roster = []

        conn.commit()
        return jsonify({
            "success": True,
            "team_id": team_id,
            "year_month": year_month,
            "columns": columns,
            "roster": roster,
            "roster_copied_from": None,
            "updated_at": updated_at
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


@app.route('/api/team-month-queues', methods=['DELETE'])
def delete_team_month_queues():
    team_id = (request.args.get('team_id') or '').strip()
    year_month = (request.args.get('year_month') or '').strip()
    if not team_id or not year_month:
        return jsonify({"error": "ต้องระบุ team_id และ year_month"}), 400

    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "DELETE FROM team_month_queues WHERE team_id = ? AND year_month = ?",
            (team_id, year_month)
        )
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

        ot_replacements_val = r["ot_replacements"] if "ot_replacements" in r.keys() else "{}"
        try:
            ot_replacements = json.loads(ot_replacements_val) if ot_replacements_val else {}
        except:
            ot_replacements = {}

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
            "ot_replacements": ot_replacements,
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
            queue_list = [str(q).strip().upper() for q in custom_queue if str(q).strip()]
        else:
            # Fetch all employees sorted by roster order (no more active/inactive distinction)
            cursor.execute("SELECT initials FROM employees ORDER BY queue_order ASC")
            all_emps = [row["initials"] for row in cursor.fetchall()]
            
            if not all_emps:
                return jsonify({"error": "ยังไม่มีรายชื่อพนักงานในระบบ โปรดเพิ่มผ่านฟอร์มสร้างวันจัดเวร"}), 400

            # Find the last shift queue to compute rotating order
            cursor.execute("SELECT queue FROM shifts ORDER BY date DESC, id DESC LIMIT 1")
            last_shift_row = cursor.fetchone()
            
            if last_shift_row:
                last_queue = json.loads(last_shift_row["queue"])
                
                # Rotate last queue by shifting left by 1
                if last_queue:
                    first = last_queue.pop(0)
                    last_queue.append(first)
                
                # Keep only employees that still exist
                queue_list = [emp for emp in last_queue if emp in all_emps]
                
                # Append any new employees not in the rotated queue
                for emp in all_emps:
                    if emp not in queue_list:
                        queue_list.append(emp)
            else:
                # Fallback to default roster order
                queue_list = all_emps

        # Auto-add any brand new employee names that the user typed in the queue textarea
        ensure_employees_exist(queue_list)

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
    ot_replacements = data.get('ot_replacements', {})

    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("PRAGMA table_info(shifts)")
        columns = [row[1] for row in cursor.fetchall()]
        if 'ot_replacements' in columns and 'leaves' in columns and 'ots' in columns:
            cursor.execute(
                "UPDATE shifts SET selections = ?, is_completed = ?, leaves = ?, ots = ?, ot_replacements = ? WHERE id = ?",
                (json.dumps(selections), is_completed, json.dumps(leaves), json.dumps(ots), json.dumps(ot_replacements), id)
            )
        elif 'leaves' in columns and 'ots' in columns:
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

    password = data.get('password', '')
    if password != MASTER_LOG_EDIT_PASSWORD:
        return jsonify({"error": "รหัสผ่านไม่ถูกต้อง กรุณาลองใหม่อีกครั้ง"}), 403
        
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
