const fs = require('fs');
const html = fs.readFileSync('C:/Users/Admin/IDEProjects/demo1/labs/switch-vlan-stp-lab.html', 'utf8');
const m = html.match(/<script>([\s\S]*?)<\/script>/);
if (m) {
    const code = m[1];
    // Check around pos 1110-1179
    const chunk = code.substring(1100, 1200);
    console.log('Chunk: [' + chunk + ']');
    for (let i = 0; i < chunk.length; i++) {
        const cc = chunk.charCodeAt(i);
        console.log(i + 1100 + ': U+' + cc.toString(16).padStart(4, '0') + ' = ' + chunk[i]);
    }
}