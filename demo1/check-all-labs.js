const fs = require('fs');
const labFiles = [
    'switch-vlan-stp-lab.html', 'arp-ip-lab.html', 'routing-ospf-lab.html',
    'vlan-nat-lab.html', 'tcp-udp-lab.html', 'app-layer-lab.html', 'comprehensive-lab.html'
];
labFiles.forEach(f => {
    const html = fs.readFileSync('C:/Users/Admin/IDEProjects/demo1/labs/' + f, 'utf8');
    const m = html.match(/<script>([\s\S]*?)<\/script>/);
    if (m) {
        const code = m[1];
        const scheduleEnd = code.indexOf('var DEVICES');
        const scheduleCode = code.substring(0, scheduleEnd);
        // Check for BOM
        if (code.charCodeAt(0) === 0xFEFF) console.log(f + ': HAS BOM!');
        // Check the schedule code is valid JS by itself
        try {
            new Function(scheduleCode);
            console.log(f + ': schedule code OK');
        } catch(e) {
            console.log(f + ': schedule code ERROR - ' + e.message);
        }
    }
});