const fs = require('fs');
const html = fs.readFileSync('C:/Users/Admin/IDEProjects/demo1/labs/switch-vlan-stp-lab.html', 'utf8');
const m = html.match(/<script>([\s\S]*?)<\/script>/);
if (m) {
    const code = m[1];
    // Test just the first 1110 chars (up to the end of schedule check code)
    try {
        new Function(code.substring(0, 1110));
        console.log('First 1110 chars: OK');
    } catch(e) {
        console.log('First 1110 chars: ERROR - ' + e.message);
    }
    // Test 1110-1200
    try {
        new Function(code.substring(1110, 1200));
        console.log('Chars 1110-1200: OK');
    } catch(e) {
        console.log('Chars 1110-1200: ERROR - ' + e.message);
    }
    // The issue might be that new Function can't handle the full code because
    // it contains browser-specific code. Let's just check the schedule part.
    const scheduleEnd = code.indexOf('var DEVICES');
    try {
        new Function(code.substring(0, scheduleEnd));
        console.log('Schedule part only: OK');
    } catch(e) {
        console.log('Schedule part only: ERROR - ' + e.message);
    }
}