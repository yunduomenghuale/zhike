const fs = require('fs');
const html = fs.readFileSync('C:/Users/Admin/IDEProjects/demo1/labs/switch-vlan-stp-lab.html', 'utf8');
const m = html.match(/<script>([\s\S]*?)<\/script>/);
if (m) {
    const code = m[1];
    // Check for BOM or zero-width chars
    for (let i = 0; i < Math.min(code.length, 500); i++) {
        const cc = code.charCodeAt(i);
        if (cc === 0xFEFF || cc === 0x200B || cc === 0x200C || cc === 0x200D || cc === 0x00AD) {
            console.log('Zero-width char at pos ' + i + ': U+' + cc.toString(16).toUpperCase());
        }
    }
    // Check for smart quotes or em-dash that might break JS
    for (let i = 0; i < code.length; i++) {
        const cc = code.charCodeAt(i);
        if (cc === 0x2018 || cc === 0x2019 || cc === 0x201C || cc === 0x201D) {
            console.log('Smart quote at pos ' + i + ': U+' + cc.toString(16).toUpperCase() + ' context: [' + code.substring(Math.max(0,i-10), i+10) + ']');
        }
    }
    console.log('First 500 chars check done. No obvious issues found in char scan.');
    
    // Try wrapping in async function to avoid document reference issues
    try {
        const wrapped = '(function(){' + code + '})';
        new Function(wrapped);
        console.log('Wrapped syntax: OK');
    } catch(e) {
        console.log('Wrapped syntax ERROR: ' + e.message);
    }
}