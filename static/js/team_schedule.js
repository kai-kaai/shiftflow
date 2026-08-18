/**
 * Team rotation schedule — single source of truth.
 * See docs/ADD_TEAM.md for how to add a new team.
 */
const TEAM_SCHEDULE = {
    cycleDays: 8,
    // วันอ้างอิงรอบ 8 วัน (วันที่ 0 = ทีมม่วง กะเช้า)
    anchorDate: '2026-06-05',
    teams: [
        {
            id: 'purple',
            name: 'ทีมสีม่วง',
            shortName: 'ทีมม่วง',
            emoji: '🟣',
            cssClass: 'purple',
            cardClass: 'team-purple',
            nameClass: '',
            morningCycleDay: 0,
            afternoonCycleDay: 2,
            morningAnchor: '2026-06-05',
            afternoonAnchor: null
        },
        {
            id: 'green',
            name: 'ทีมสีเขียว',
            shortName: 'ทีมเขียว',
            emoji: '🟢',
            cssClass: 'green',
            cardClass: 'team-green',
            nameClass: '',
            morningCycleDay: 1,
            afternoonCycleDay: 3,
            morningAnchor: null,
            afternoonAnchor: null
        },
        {
            id: 'gray',
            name: 'ทีมเทา',
            shortName: 'ทีมเทา',
            emoji: '⚪',
            cssClass: 'gray',
            cardClass: 'team-gray',
            nameClass: 'team-name-gray',
            morningCycleDay: 2,
            afternoonCycleDay: 4,
            morningAnchor: '2026-07-01',
            afternoonAnchor: '2026-07-03'
        }
    ]
};

function parseLocalDate(dateStr) {
    const parts = dateStr.split('-');
    if (parts.length < 3) return null;
    return new Date(parseInt(parts[0], 10), parseInt(parts[1], 10) - 1, parseInt(parts[2], 10));
}

function getRotationDayIndex(dateStr) {
    const date = parseLocalDate(dateStr);
    const anchor = parseLocalDate(TEAM_SCHEDULE.anchorDate);
    if (!date || !anchor) return null;

    const diffDays = Math.round((date.getTime() - anchor.getTime()) / (1000 * 60 * 60 * 24));
    let remainder = diffDays % TEAM_SCHEDULE.cycleDays;
    if (remainder < 0) remainder += TEAM_SCHEDULE.cycleDays;
    return remainder;
}

function getTeamForDate(dateStr, shiftType) {
    if (!dateStr || !shiftType) return null;

    const dayIndex = getRotationDayIndex(dateStr);
    if (dayIndex === null) return null;

    const cycleField = shiftType === 'M8/A14' ? 'morningCycleDay' : 'afternoonCycleDay';
    const matched = TEAM_SCHEDULE.teams.find(team => team[cycleField] === dayIndex);
    return matched ? matched.id : null;
}

function getTeamDefinition(teamId) {
    return TEAM_SCHEDULE.teams.find(team => team.id === teamId) || null;
}

function getTeamDisplay(teamId) {
    const team = getTeamDefinition(teamId);
    if (!team) return null;

    const nameHtml = team.nameClass
        ? `<span class="${team.nameClass}">${team.shortName}</span>`
        : team.shortName;
    const strongOpen = team.nameClass ? `<strong class="${team.nameClass}">` : '<strong>';

    return {
        cardClass: team.cardClass,
        cardLabel: nameHtml,
        inlineLabel: ` | ${team.emoji} ${team.shortName}`,
        helperClass: team.cssClass,
        helperHtml: `${team.emoji} ทีมที่ปฏิบัติหน้าที่ตามเงื่อนไข: ${strongOpen}${team.name}</strong>`,
        refLabel: `${team.emoji} ${team.nameClass ? `<span class="${team.nameClass}">${team.name}</span>` : team.name}`
    };
}

function getRotationPatternTable() {
    const rows = [];
    for (let day = 0; day < TEAM_SCHEDULE.cycleDays; day += 1) {
        const morningTeam = TEAM_SCHEDULE.teams.find(team => team.morningCycleDay === day);
        const afternoonTeam = TEAM_SCHEDULE.teams.find(team => team.afternoonCycleDay === day);
        rows.push({
            cycleDay: day,
            morning: morningTeam ? morningTeam.id : null,
            afternoon: afternoonTeam ? afternoonTeam.id : null
        });
    }
    return rows;
}

function findTeamScheduleConflicts(candidateTeam, teams = TEAM_SCHEDULE.teams) {
    const conflicts = [];
    teams.forEach(existing => {
        if (candidateTeam.id && existing.id === candidateTeam.id) {
            conflicts.push(`id ซ้ำ: ${candidateTeam.id}`);
        }
        if (candidateTeam.morningCycleDay === existing.morningCycleDay) {
            conflicts.push(`กะเช้าวันที่ ${candidateTeam.morningCycleDay} ถูกใช้โดย ${existing.id}`);
        }
        if (candidateTeam.afternoonCycleDay === existing.afternoonCycleDay) {
            conflicts.push(`กะบ่ายดึกวันที่ ${candidateTeam.afternoonCycleDay} ถูกใช้โดย ${existing.id}`);
        }
    });
    return conflicts;
}

/**
 * สร้าง config entry สำหรับทีมใหม่จากวัน anchor
 * ตัวอย่าง:
 * buildTeamConfigEntry({
 *   id: 'orange',
 *   name: 'ทีมส้ม',
 *   shortName: 'ทีมส้ม',
 *   emoji: '🟠',
 *   cssClass: 'orange',
 *   cardClass: 'team-orange',
 *   nameClass: 'team-name-orange',
 *   morningAnchor: '2026-06-10',
 *   afternoonAnchor: '2026-06-12'
 * });
 */
function buildTeamConfigEntry(options) {
    const morningCycleDay = options.morningAnchor != null
        ? getRotationDayIndex(options.morningAnchor)
        : options.morningCycleDay;
    const afternoonCycleDay = options.afternoonAnchor != null
        ? getRotationDayIndex(options.afternoonAnchor)
        : options.afternoonCycleDay;

    const entry = {
        id: options.id,
        name: options.name,
        shortName: options.shortName || options.name,
        emoji: options.emoji || '🔵',
        cssClass: options.cssClass || options.id,
        cardClass: options.cardClass || `team-${options.id}`,
        nameClass: options.nameClass || '',
        morningCycleDay,
        afternoonCycleDay,
        morningAnchor: options.morningAnchor || null,
        afternoonAnchor: options.afternoonAnchor || null
    };

    const conflicts = findTeamScheduleConflicts(entry);
    return { entry, conflicts, isValid: conflicts.length === 0 };
}

/**
 * รายการวันทำงาน (คอลัมน์) ของทีมในเดือนที่กำหนด
 * เรียงตามวันที่ แล้วกะเช้า (M8/A14) ก่อนบ่ายดึก (A+N)
 */
function listTeamWorkColumns(teamId, year, month) {
    if (!teamId || !year || !month) return [];

    const y = parseInt(year, 10);
    const m = parseInt(month, 10);
    if (!y || !m || m < 1 || m > 12) return [];

    const daysInMonth = new Date(y, m, 0).getDate();
    const columns = [];

    for (let day = 1; day <= daysInMonth; day += 1) {
        const dateStr = `${y}-${String(m).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
        ['M8/A14', 'A+N'].forEach(shiftType => {
            if (getTeamForDate(dateStr, shiftType) === teamId) {
                columns.push({
                    date: dateStr,
                    shift_type: shiftType,
                    queue: [],
                    supervisor: ''
                });
            }
        });
    }
    return columns;
}

function formatYearMonth(year, month) {
    return `${parseInt(year, 10)}-${String(parseInt(month, 10)).padStart(2, '0')}`;
}

function formatQueueColumnHeader(dateStr, shiftType) {
    const date = parseLocalDate(dateStr);
    if (!date) {
        return { dateLine: dateStr || '', shiftLine: shiftType || '' };
    }
    const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    const day = date.getDate();
    const mon = months[date.getMonth()];
    const year = date.getFullYear();
    return {
        dateLine: `${day}-${mon}-${year}`,
        shiftLine: shiftType || ''
    };
}

/** หมุนคิวซ้าย 1 ตำแหน่ง (คนแรกไปท้าย) */
function rotateQueueLeft1(queue) {
    if (!queue || queue.length === 0) return [];
    const next = queue.slice(1);
    next.push(queue[0]);
    return next;
}

/** หมุนคิวให้ชื่อที่กำหนดอยู่ตำแหน่งแรก ถ้าไม่มีชื่อนั้นคืนคิวเดิม */
function rotateQueueToStart(queue, startName) {
    if (!queue || queue.length === 0) return [];
    const start = String(startName || '').trim().toUpperCase();
    if (!start) return queue.slice();
    const idx = queue.findIndex(name => String(name).trim().toUpperCase() === start);
    if (idx <= 0) return queue.slice();
    return queue.slice(idx).concat(queue.slice(0, idx));
}

const QUEUE_WORKING_LIMIT = 13;

function getWorkingRosterInitials(roster) {
    return (roster || [])
        .filter(person => person && person.working)
        .map(person => String(person.initials || '').trim().toUpperCase())
        .filter(Boolean);
}

/**
 * รวมโครงคอลัมน์จากปฏิทินทีม กับข้อมูลที่บันทึกไว้
 * โครงจากปฏิทินเป็น source of truth ว่ามีกี่วันทำงาน
 */
function mergeTeamWorkColumns(skeletonColumns, savedColumns) {
    const savedMap = new Map();
    (savedColumns || []).forEach(col => {
        if (!col || !col.date || !col.shift_type) return;
        savedMap.set(`${col.date}|${col.shift_type}`, col);
    });

    return (skeletonColumns || []).map(skel => {
        const key = `${skel.date}|${skel.shift_type}`;
        const saved = savedMap.get(key);
        if (!saved) {
            return {
                date: skel.date,
                shift_type: skel.shift_type,
                queue: [],
                supervisor: ''
            };
        }
        const queue = Array.isArray(saved.queue)
            ? saved.queue.map(q => String(q).trim().toUpperCase()).filter(Boolean)
            : [];
        return {
            date: skel.date,
            shift_type: skel.shift_type,
            queue,
            supervisor: saved.supervisor || ''
        };
    });
}