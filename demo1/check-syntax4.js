const fs = require('fs');
const html = fs.readFileSync('C:/Users/Admin/IDEProjects/demo1/labs/switch-vlan-stp-lab.html', 'utf8');
const m = html.match(/<script>([\s\S]*?)<\/script>/);
if (m) {
    const code = m[1];
    // Binary search for the error
    let lo = 0, hi = code.length;
    while (hi - lo > 100) {
        const mid = Math.floor((lo + hi) / 2);
        try {
            new Function(code.substring(0, mid));
            lo = mid;
        } catch(e) {
            hi = mid;
        }
    }
    console.log('Error likely between pos ' + lo + ' and ' + hi);
    console.log('Context: [' + code.substring(lo, hi) + ']');
    // Show chars around the error
    for (let i = lo; i < hi; i++) {
        const cc = code.charCodeAt(i);
        if (cc > 127 || cc < 32 && cc !== 10 && cc !== 13) {
            console.log('Pos ' + i + ': U+' + cc.toString(16).toUpperCase() + ' char: ' + code[i]);
        }
    }
}