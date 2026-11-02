const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '..');
const context = vm.createContext({
    window: { innerWidth: 1400, addEventListener() {} },
    document: { addEventListener() {} },
    console,
    Date,
    confirm: () => true,
});
vm.runInContext(fs.readFileSync(path.join(root, 'static/js/team_schedule.js'), 'utf8'), context);
const html = fs.readFileSync(path.join(root, 'templates/index.html'), 'utf8');
for (const match of html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)) {
    vm.runInContext(match[1], context);
}
const run = source => vm.runInContext(source, context);

for (const type of ['M8/A14', 'A+N']) {
    for (const date of ['2026-10-31', '2026-11-01']) {
        run(`selectedShift = { date: '${date}', shift_type: '${type}' };`);
        assert.equal(run(`getShiftPreviewLogs().some(log => log.id === 'FDO3')`), date >= '2026-11-01');
        assert.equal(run(`validateChoiceFormat('FDO3', ${type === 'M8/A14'})`), date >= '2026-11-01');
        if (type === 'A+N') {
            assert.equal(run(`getShiftPreviewLogs().some(log => log.id === 'A6')`), date >= '2026-11-01');
            assert.equal(run(`validateChoiceFormat('A6', false)`), date >= '2026-11-01');
        }
    }
}
assert.equal(run(`getQueueWorkingLimit('2026-10-31', 'A+N')`), 13);
assert.equal(run(`getQueueWorkingLimit('2026-11-01', 'A+N')`), 14);
assert.equal(run(`getQueueWorkingLimit('2026-11-01', 'M8/A14')`), 13);
assert.equal(run(`planCacheKey('purple', '2026-10', 'A+N') === planCacheKey('purple', '2026-10', 'M8/A14')`), true);
assert.equal(run(`planCacheKey('purple', '2026-11', 'A+N') === planCacheKey('purple', '2026-11', 'M8/A14')`), false);

for (const type of ['M8/A14', 'A+N']) {
    run(`
        queueRoomYear = 2026;
        queueRoomMonth = 11;
        queueRoomShiftType = '${type}';
        queueRoomColumns = listTeamWorkColumns('purple', 2026, 11, queueRoomGroup());
        queueRoomRoster = Array.from({ length: queueRoomWorkingLimit() }, (_, i) => ({ initials: 'E' + i, working: true }));
        queueRoomColumns[0].queue = ['E2'];
        syncQueueRoomColumnsFromDom = () => {};
        renderQueueRoomTable = () => {};
        updateQueueRoomMeta = () => {};
        showToast = () => {};
        runQueueRoomQue();
    `);
    assert.equal(run(`queueRoomColumns.every(col => col.shift_type === '${type}')`), true);
    assert.equal(run(`queueRoomColumns.every(col => col.queue.length === queueRoomWorkingLimit())`), true);
    assert.equal(run(`queueRoomColumns[0].queue[0]`), 'E2');
    assert.equal(run(`queueRoomColumns[1].queue[0]`), 'E3');
    assert.equal(run(`queueRoomColumns[1].queue.at(-1)`), 'E2');
}
console.log('PASS: historical/new preview choices, 13/14 staff limits, separate cache keys, and Run Que for both shift groups');
