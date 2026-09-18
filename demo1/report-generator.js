const fs = require('fs');
const zlib = require('zlib');
const path = require('path');
const { execSync } = require('child_process');

const TEMPLATE_PATH = path.join(__dirname, 'report-template.docx');
const REPORTS_DIR = path.join(__dirname, 'reports');

if (!fs.existsSync(REPORTS_DIR)) {
    fs.mkdirSync(REPORTS_DIR, { recursive: true });
}

const LAB_INFO = {
    'switch-vlan-stp-lab': {
        name: '交换机与VLAN综合实验',
        objectives: [
            '理解交换机MAC地址自学习原理',
            '掌握VLAN的创建、端口划分与隔离验证',
            '掌握Trunk链路配置实现跨交换机VLAN通信',
            '理解STP生成树协议的工作原理与根桥选举'
        ]
    },
    'arp-ip-lab': {
        name: 'ARP与IP子网综合实验',
        objectives: [
            '理解ARP协议的工作原理（请求-响应过程）',
            '掌握同网段和跨网段ARP通信的差异',
            '学会配置和删除静态ARP条目',
            '掌握子网划分方法与子网掩码的作用',
            '理解路由聚合与最长前缀匹配原则'
        ]
    },
    'routing-ospf-lab': {
        name: '路由协议综合实验',
        objectives: [
            '掌握静态路由的配置与验证方法',
            '理解RIP动态路由协议的工作原理',
            '掌握OSPF单区域配置与邻居关系建立',
            '理解RIPv1与RIPv2的区别及水平分割机制',
            '掌握多区域OSPF配置与路由聚合',
            '对比三种路由方式的差异与适用场景'
        ]
    },
    'vlan-nat-lab': {
        name: 'VLAN互连与NAT综合实验',
        objectives: [
            '掌握三层交换机VLANIF接口实现VLAN间路由',
            '理解单臂路由器互连VLAN的方式',
            '掌握静态NAT、动态NAT和NAPT的配置与区别',
            '理解内网到外网的完整通信流程'
        ]
    },
    'tcp-udp-lab': {
        name: '传输层协议综合实验',
        objectives: [
            '深入理解TCP三次握手与四次挥手的完整过程',
            '掌握TCP状态变迁机制',
            '理解TCP流量控制与拥塞控制机制',
            '理解UDP无连接通信的特点与报文格式',
            '对比TCP与UDP协议的差异'
        ]
    },
    'app-layer-lab': {
        name: '应用层协议综合实验',
        objectives: [
            '理解DHCP协议的Discover-Offer-Request-ACK四步交互过程',
            '掌握DNS域名解析的递归查询流程与报文格式',
            '理解HTTP请求响应的完整过程与报文格式',
            '掌握DHCP中继代理的工作原理',
            '掌握应用层协议与传输层协议的协作关系'
        ]
    },
    'comprehensive-lab': {
        name: '计算机网络综合实验',
        objectives: [
            '综合运用VLAN、路由、NAT、DHCP、DNS、HTTP等知识',
            '完成企业网络从内网搭建到外网访问的全流程配置',
            '理解各层协议之间的协作关系',
            '培养网络故障排查与综合配置能力'
        ]
    }
};

function ensureTemplate() {
    if (!fs.existsSync(TEMPLATE_PATH)) {
        const srcPath = 'c:\\Users\\Admin\\Desktop\\实验报告模板.docx';
        if (fs.existsSync(srcPath)) {
            fs.copyFileSync(srcPath, TEMPLATE_PATH);
        } else {
            throw new Error('实验报告模板文件不存在');
        }
    }
}

let _fontInfo = null;
function getFontInfo() {
    return _fontInfo;
}

function generatePdfViaWord(docxPath, pdfPath) {
    const psScript = `$word = New-Object -ComObject Word.Application
$word.Visible = $false
$word.DisplayAlerts = 0
try {
    $doc = $word.Documents.Open("${docxPath.replace(/\\/g, '\\\\')}")
    $doc.SaveAs([ref]"${pdfPath.replace(/\\/g, '\\\\')}", [ref]17)
    $doc.Close()
} catch {
    Write-Output "Error: $_"
} finally {
    $word.Quit()
}`;
    const psPath = path.join(REPORTS_DIR, '_convert_pdf.ps1');
    fs.writeFileSync(psPath, psScript, 'utf8');

    try {
        execSync('powershell -ExecutionPolicy Bypass -File "' + psPath + '"', {
            timeout: 60000,
            windowsHide: true,
            cwd: REPORTS_DIR
        });
    } catch (e) {
        console.error('Word COM转换PDF失败:', e.message);
    }

    try { fs.unlinkSync(psPath); } catch (e) {}

    return fs.existsSync(pdfPath);
}

function crc32(buf) {
    let crc = 0xFFFFFFFF;
    const table = [];
    for (let i = 0; i < 256; i++) {
        let c = i;
        for (let j = 0; j < 8; j++) {
            if (c & 1) c = 0xEDB88320 ^ (c >>> 1);
            else c = c >>> 1;
        }
        table[i] = c;
    }
    for (let i = 0; i < buf.length; i++) {
        crc = table[(crc ^ buf[i]) & 0xFF] ^ (crc >>> 8);
    }
    return (crc ^ 0xFFFFFFFF) >>> 0;
}

function createZip(files) {
    const chunks = [];
    const centralDirEntries = [];
    let offset = 0;

    for (const file of files) {
        const fileNameBytes = Buffer.from(file.name, 'utf8');
        const fileData = Buffer.isBuffer(file.data) ? file.data : Buffer.from(file.data, 'utf8');
        const compressed = zlib.deflateRawSync(fileData);
        const crc = crc32(fileData);

        const localHeader = Buffer.alloc(30);
        localHeader.writeUInt32LE(0x04034b50, 0);
        localHeader.writeUInt16LE(20, 4);
        localHeader.writeUInt16LE(0x0800, 6);
        localHeader.writeUInt16LE(8, 8);
        localHeader.writeUInt16LE(0, 10);
        localHeader.writeUInt16LE(0, 12);
        localHeader.writeUInt32LE(crc, 14);
        localHeader.writeUInt32LE(compressed.length, 18);
        localHeader.writeUInt32LE(fileData.length, 22);
        localHeader.writeUInt16LE(fileNameBytes.length, 26);
        localHeader.writeUInt16LE(0, 28);

        chunks.push(localHeader, fileNameBytes, compressed);

        const cdEntry = Buffer.alloc(46);
        cdEntry.writeUInt32LE(0x02014b50, 0);
        cdEntry.writeUInt16LE(20, 4);
        cdEntry.writeUInt16LE(20, 6);
        cdEntry.writeUInt16LE(0x0800, 8);
        cdEntry.writeUInt16LE(8, 10);
        cdEntry.writeUInt16LE(0, 12);
        cdEntry.writeUInt16LE(0, 14);
        cdEntry.writeUInt32LE(crc, 16);
        cdEntry.writeUInt32LE(compressed.length, 20);
        cdEntry.writeUInt32LE(fileData.length, 24);
        cdEntry.writeUInt16LE(fileNameBytes.length, 28);
        cdEntry.writeUInt16LE(0, 30);
        cdEntry.writeUInt16LE(0, 32);
        cdEntry.writeUInt16LE(0, 34);
        cdEntry.writeUInt16LE(0, 36);
        cdEntry.writeUInt32LE(0, 38);
        cdEntry.writeUInt32LE(offset, 42);

        centralDirEntries.push(Buffer.concat([cdEntry, fileNameBytes]));
        offset += localHeader.length + fileNameBytes.length + compressed.length;
    }

    const cdOffset = offset;
    const centralDirBuf = Buffer.concat(centralDirEntries);
    let cdSize = centralDirBuf.length;

    const endRecord = Buffer.alloc(22);
    endRecord.writeUInt32LE(0x06054b50, 0);
    endRecord.writeUInt16LE(0, 4);
    endRecord.writeUInt16LE(0, 6);
    endRecord.writeUInt16LE(files.length, 8);
    endRecord.writeUInt16LE(files.length, 10);
    endRecord.writeUInt32LE(cdSize, 12);
    endRecord.writeUInt32LE(cdOffset, 16);
    endRecord.writeUInt16LE(0, 20);

    return Buffer.concat([...chunks, centralDirBuf, endRecord]);
}

function extractZip(filePath) {
    const data = fs.readFileSync(filePath);
    const files = [];
    let pos = 0;

    while (pos < data.length - 4) {
        const sig = data.readUInt32LE(pos);
        if (sig !== 0x04034b50) break;

        const compressionMethod = data.readUInt16LE(pos + 8);
        const compressedSize = data.readUInt32LE(pos + 18);
        const uncompressedSize = data.readUInt32LE(pos + 22);
        const fileNameLength = data.readUInt16LE(pos + 26);
        const extraFieldLength = data.readUInt16LE(pos + 28);

        const fileName = data.toString('utf8', pos + 30, pos + 30 + fileNameLength);
        const fileDataStart = pos + 30 + fileNameLength + extraFieldLength;
        const fileDataEnd = fileDataStart + compressedSize;
        const compressedData = data.slice(fileDataStart, fileDataEnd);

        let fileContent;
        if (compressionMethod === 0) {
            fileContent = compressedData;
        } else if (compressionMethod === 8) {
            fileContent = zlib.inflateRawSync(compressedData);
        } else {
            fileContent = compressedData;
        }

        files.push({ name: fileName, data: fileContent });
        pos = fileDataEnd;
    }

    return files;
}

function escapeXml(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&apos;');
}

function makeRun(text) {
    return '<w:r><w:rPr><w:rFonts w:hint="eastAsia"/><w:sz w:val="24"/><w:szCs w:val="24"/><w:vertAlign w:val="baseline"/><w:lang w:val="en-US" w:eastAsia="zh-CN"/></w:rPr><w:t xml:space="preserve">' + escapeXml(text) + '</w:t></w:r>';
}

function makeParagraph(text) {
    return '<w:p><w:pPr><w:rPr><w:rFonts w:hint="eastAsia"/><w:sz w:val="24"/><w:szCs w:val="24"/><w:vertAlign w:val="baseline"/><w:lang w:val="en-US" w:eastAsia="zh-CN"/></w:rPr></w:pPr>' + makeRun(text) + '</w:p>';
}

function findAllTcElements(str) {
    const elements = [];
    let pos = 0;
    while (pos < str.length) {
        const start = str.indexOf('<w:tc>', pos);
        if (start === -1) break;
        const end = str.indexOf('</w:tc>', start);
        if (end === -1) break;
        elements.push({ start, end: end + '</w:tc>'.length });
        pos = end + '</w:tc>'.length;
    }
    return elements;
}

function extractTcText(str) {
    const matches = str.match(/<w:t[^>]*>([^<]*)<\/w:t>/g) || [];
    return matches.map(m => m.replace(/<w:t[^>]*>/, '').replace('</w:t>', '')).join('');
}

function fillTemplateXml(templateXml, reportData) {
    let xml = templateXml;

    xml = xml.replace('<w:gridCol w:w="1227"/>', '<w:gridCol w:w="1094"/>');
    xml = xml.replace('<w:gridCol w:w="834"/>', '<w:gridCol w:w="1100"/>');
    xml = xml.replace('<w:gridCol w:w="1188"/>', '<w:gridCol w:w="1055"/>');

    xml = xml.replace(/<w:tcW w:w="1227"/g, '<w:tcW w:w="1094"');
    xml = xml.replace(/<w:tcW w:w="834"/g, '<w:tcW w:w="1100"');
    xml = xml.replace(/<w:tcW w:w="1188"/g, '<w:tcW w:w="1055"');

    const cellFillMap = [
        { label: '课程名称', value: reportData.courseName || '计算机网络' },
        { label: '实验名称', value: reportData.labName || '' },
        { label: '实验成绩', value: String(reportData.totalScore || 0) },
        { label: '基础分', value: String(reportData.baseScore || 0) },
        { label: '综评分', value: String(reportData.comprehensiveScore || 0) },
        { label: '学号', value: reportData.studentId || '' },
        { label: '姓名', value: reportData.studentName || '' },
        { label: '班级', value: reportData.className || '' },
        { label: '实验日期', value: reportData.experimentDate || '' }
    ];

    let tcElements = findAllTcElements(xml);
    const replacements = [];

    for (const { label, value } of cellFillMap) {
        for (let i = 0; i < tcElements.length - 1; i++) {
            const tcContent = xml.substring(tcElements[i].start, tcElements[i].end);
            const tcText = extractTcText(tcContent);
            if (tcText === label) {
                const valueTc = tcElements[i + 1];
                const valueTcContent = xml.substring(valueTc.start, valueTc.end);
                const tcPrMatch = valueTcContent.match(/<w:tcPr>[\s\S]*?<\/w:tcPr>/);
                const tcPr = tcPrMatch ? tcPrMatch[0] : '';

                const newValueTc = '<w:tc>' + tcPr +
                    '<w:p><w:pPr><w:jc w:val="center"/><w:rPr><w:rFonts w:hint="eastAsia"/><w:sz w:val="24"/><w:szCs w:val="24"/><w:vertAlign w:val="baseline"/><w:lang w:val="en-US" w:eastAsia="zh-CN"/></w:rPr></w:pPr>' +
                    makeRun(value) +
                    '</w:p></w:tc>';

                replacements.push({ start: valueTc.start, end: valueTc.end, newContent: newValueTc });
                break;
            }
        }
    }

    replacements.sort((a, b) => b.start - a.start);
    for (const rep of replacements) {
        xml = xml.substring(0, rep.start) + rep.newContent + xml.substring(rep.end);
    }

    const sectionFillMap = [
        { label: '实验目的：', content: reportData.objectives || '' },
        { label: '实验平台：', content: reportData.platform || '计算机网络虚拟仿真实验平台' },
        { label: '实验步骤：', content: reportData.steps || '' },
        { label: '实验结论：', content: reportData.conclusion || '' }
    ];

    tcElements = findAllTcElements(xml);
    const sectionReplacements = [];

    for (const { label, content } of sectionFillMap) {
        for (let i = 0; i < tcElements.length; i++) {
            const tcContent = xml.substring(tcElements[i].start, tcElements[i].end);
            const tcText = extractTcText(tcContent);
            if (tcText === label) {
                const tcEl = tcElements[i];
                const tcPrMatch = tcContent.match(/<w:tcPr>[\s\S]*?<\/w:tcPr>/);
                const tcPr = tcPrMatch ? tcPrMatch[0] : '';

                const contentLines = content.split('\n').filter(l => l.trim());
                let contentParagraphs = '';
                for (const line of contentLines) {
                    contentParagraphs += makeParagraph(line);
                }

                const newTc = '<w:tc>' + tcPr +
                    '<w:p><w:pPr><w:rPr><w:rFonts w:hint="eastAsia"/><w:sz w:val="24"/><w:szCs w:val="24"/><w:vertAlign w:val="baseline"/><w:lang w:val="en-US" w:eastAsia="zh-CN"/></w:rPr></w:pPr>' +
                    makeRun(label) +
                    '</w:p>' + contentParagraphs +
                    '</w:tc>';

                sectionReplacements.push({ start: tcEl.start, end: tcEl.end, newContent: newTc });
                break;
            }
        }
    }

    sectionReplacements.sort((a, b) => b.start - a.start);
    for (const rep of sectionReplacements) {
        xml = xml.substring(0, rep.start) + rep.newContent + xml.substring(rep.end);
    }

    xml = xml.replace('<w:t>实 验 报 告</w:t>', '<w:t>实验报告</w:t>');

    return xml;
}

function generateDocx(reportData) {
    ensureTemplate();
    const files = extractZip(TEMPLATE_PATH);
    const updatedFiles = files.map(f => {
        if (f.name === 'word/document.xml') {
            const newXml = fillTemplateXml(f.data.toString('utf8'), reportData);
            return { name: f.name, data: Buffer.from(newXml, 'utf8') };
        }
        return f;
    });
    return createZip(updatedFiles);
}

function generateReport(reportData) {
    const labInfo = LAB_INFO[reportData.labId] || {};
    const fullData = {
        courseName: '计算机网络',
        labName: labInfo.name || reportData.labName || '',
        totalScore: reportData.totalScore || 0,
        baseScore: reportData.baseScore || 0,
        comprehensiveScore: reportData.comprehensiveScore || 0,
        studentId: reportData.studentId || '',
        studentName: reportData.studentName || '',
        className: reportData.className || '',
        experimentDate: reportData.experimentDate || new Date().toLocaleDateString('zh-CN'),
        objectives: (labInfo.objectives || []).join('\n'),
        platform: '计算机网络虚拟仿真实验平台',
        steps: reportData.steps || '',
        conclusion: reportData.conclusion || '',
        labId: reportData.labId || ''
    };

    const docxBuffer = generateDocx(fullData);
    const timestamp = Date.now();
    const docxFileName = 'report_' + fullData.studentId + '_' + fullData.labId + '_' + timestamp + '.docx';
    const pdfFileName = 'report_' + fullData.studentId + '_' + fullData.labId + '_' + timestamp + '.pdf';

    const docxPath = path.join(REPORTS_DIR, docxFileName);
    const pdfPath = path.join(REPORTS_DIR, pdfFileName);

    fs.writeFileSync(docxPath, docxBuffer);

    generatePdfViaWord(docxPath, pdfPath);

    return {
        docxPath: docxPath,
        pdfPath: pdfPath,
        docxFileName: docxFileName,
        pdfFileName: pdfFileName
    };
}

module.exports = { generateReport, LAB_INFO };
