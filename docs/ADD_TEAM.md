# คู่มือเพิ่มทีมใหม่ (Team Rotation)

ใช้เมื่อต้องการเพิ่มทีม เช่น **"เพิ่มทีมส้ม กะเช้า วันที่ 1 ส.ค. 2026"**

---

## แนวคิดหลัก

- รอบเวร **8 วัน** (`TEAM_SCHEDULE.cycleDays`)
- อ้างอิงจาก **5 มิ.ย. 2026** = วันที่ 0 ในรอบ (`TEAM_SCHEDULE.anchorDate`)
- แต่ละทีมมี 2 ช่วงในรอบ:
  - `morningCycleDay` → กะเช้า `M8/A14`
  - `afternoonCycleDay` → กะบ่ายดึก `A+N`
- วันเดียวกัน **คนละกะ** สามารถเป็นคนละทีมได้ (เช่น วันที่ 2: เช้า=เทา, บ่ายดึก=ม่วง)

### ตารางปัจจุบัน

| วันในรอบ | กะเช้า | กะบ่ายดึก |
|:---:|:---|:---|
| 0 | ม่วง | หยุด |
| 1 | เขียว | หยุด |
| 2 | เทา | ม่วง |
| 3 | หยุด | เขียว |
| 4 | หยุด | เทา |
| 5–7 | หยุด | หยุด |

---

## วิธีเพิ่มทีมใหม่ (เช่น ทีมส้ม)

### ขั้นที่ 1 — วางแผนวัน anchor

ระบุวันเริ่มกะเช้าและกะบ่ายดึก เช่น **"เพิ่มทีมส้ม กะเช้า 10 มิ.ย. 2026"**:

- กะเช้า: `2026-06-10`
- กะบ่ายดึก: `2026-06-12` (มักห่าง 2 วันในรอบ ตาม pattern เดิม)

> ถ้า `buildTeamConfigEntry()` ขึ้น `conflicts` แปลว่าวันนั้นมีทีมอื่นอยู่แล้ว — เลือกวันอื่นในรอบที่ยังว่าง (ปัจจุบัน: กะเช้าวัน 5–7, กะบ่ายดึกวัน 5–7)

### ขั้นที่ 2 — สร้าง config ด้วย helper (ใน Browser Console)

เปิดแอป → DevTools Console แล้วรัน:

```javascript
buildTeamConfigEntry({
  id: 'orange',
  name: 'ทีมส้ม',
  shortName: 'ทีมส้ม',
  emoji: '🟠',
  cssClass: 'orange',
  cardClass: 'team-orange',
  nameClass: 'team-name-orange',
  morningAnchor: '2026-06-10',
  afternoonAnchor: '2026-06-12'
});
```

ผลลัพธ์:
- `entry` → object สำหรับ copy ไปใส่ใน `TEAM_SCHEDULE.teams`
- `conflicts` → รายการชนกับทีมเดิม (ต้องว่างก่อนเพิ่ม)
- `isValid` → `true` = เพิ่มได้

ดู pattern ทั้งรอบ:

```javascript
getRotationPatternTable();
```

---

## ไฟล์ที่ต้องแก้

### 1. `static/js/team_schedule.js` (หลัก)

เพิ่ม object ใหม่ใน `TEAM_SCHEDULE.teams`:

```javascript
{
    id: 'orange',
    name: 'ทีมส้ม',
    shortName: 'ทีมส้ม',
    emoji: '🟠',
    cssClass: 'orange',
    cardClass: 'team-orange',
    nameClass: 'team-name-orange',
    morningCycleDay: 5,      // จาก buildTeamConfigEntry()
    afternoonCycleDay: 7,    // จาก buildTeamConfigEntry()
    morningAnchor: '2026-06-10',
    afternoonAnchor: '2026-06-12'
}
```

> Logic อื่นๆ (`getTeamForDate`, แนะนำคิว, UI) อ่านจาก config นี้อัตโนมัติ — **ไม่ต้องแก้** `templates/index.html` สำหรับ logic ทีม (แก้แค่ CSS สีใหม่)

### 2. `static/css/app.css`

เพิ่มสีทีมใหม่:

```css
:root {
    --team-orange: #F97316;
    --team-orange-soft: #FFEDD5;
}

.shift-card.team-orange { --card-team: var(--team-orange); }

.team-helper.orange {
    background-color: var(--team-orange-soft);
    color: #9A3412;
    border: 1px solid rgba(249, 115, 22, 0.25);
}

.team-name-orange {
    color: var(--team-orange);
}
```

---

## Checklist ก่อนปิดงาน

- [ ] `buildTeamConfigEntry()` คืน `isValid: true`
- [ ] กะเช้า/บ่ายดึกไม่ชนกับทีมเดิมในวัน+กะเดียวกัน
- [ ] ทดสอบวัน anchor ใน modal **สร้างตารางเวรใหม่** แสดงชื่อทีมถูกต้อง
- [ ] Card ในหน้า Dashboard แสดงทีมและสีถูกต้อง
- [ ] คิวแนะนำอ้างอิงกะล่าสุดของทีมเดียวกัน (หมุนคิวซ้าย 1)

---

## คำสั่งที่ใช้บ่อย

| คำสั่ง | 用途 |
|:---|:---|
| `getRotationDayIndex('2026-06-10')` | ดูว่าวันนั้นอยู่ลำดับที่เท่าไรในรอบ 8 วัน |
| `getTeamForDate('2026-06-10', 'M8/A14')` | ดูทีมของวัน+กะนั้น |
| `buildTeamConfigEntry({...})` | สร้าง config ทีมใหม่ |
| `getRotationPatternTable()` | ดูตารางรอบเต็ม |

---

## หมายเหตุ

- สมาชิกทีมเก็บในห้องจัดคิว แยกตามทีม+เดือน (`roster_json`) คนอยู่ได้หลายทีม คนไม่ทำงานเดือนนั้นแสดงเป็น `(ชื่อ)`
- จำนวนคนต่อกะ = **13 คน** (กำหนดใน `getSuggestedQueue()` ใน `index.html`)
- ถ้ารอบ 8 วันเต็มแล้วต้องเพิ่มทีม → ต้องขยาย `cycleDays` และออกแบบ pattern ใหม่ทั้งระบบ