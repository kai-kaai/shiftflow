# Master Log — 1 November 2026

Implemented on `update-master-log` from the supplied morning and afternoon/night reference images.

- Shifts dated before `2026-11-01` keep the original layout and Master Log overrides.
- Shifts dated `2026-11-01` onward use the November version. New shifts inherit overrides from that version only.
- M8/A14 remains 13 working employees. The assignment preview includes FDO 3; the Master Log has the new F1/F2 rotation and removes GMC+F2 combinations. The view includes W/S A14 duties through 1500 UTC.
- A+N has 14 working employees. The assignment preview includes A6 and FDO 3. Afternoon, night and FDO duties match the new reference.
- The queue room has a shift selector from November onward. Rosters, working flags, queue order, supervisors, Run Que, saved plans, suggestions, full-screen views and image filenames are separate for M8/A14 and A+N.
- The original combined queue plans are retained. Until a group is saved separately, it reads the matching columns from a legacy combined plan. Previous rosters carry forward within the same group, with combined legacy rosters as a fallback. Select the additional working employee for A+N before running its 14-person queue.

Schema migration runs automatically on startup in one transaction. `team_month_queues` is unique by `(team_id, year_month, shift_group)`; empty `shift_group` identifies a legacy combined plan. November Master Logs use separate `template_logs` keys ending in `@2026-11`, preserving original customizations.

Validation:

```sh
python3 -m unittest discover -s tests -v
node tests/test_queue_room.js
```

Tests use a temporary SQLite database. `SHIFTFLOW_DB_PATH` can select a separate database for development or testing.
