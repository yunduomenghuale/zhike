"""生成题库导入测试用 docx 文件（与 test/e2e/import-e2e-v1.txt 同构：7 题 5 题型）。
第 4 题题干与题库已有题目重复，用于查重（skipped）路径验证。
输出：docs/测试文件目录/题目导入测试样例.docx
"""
from docx import Document
from docx.shared import Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH

doc = Document()

# 正文默认字体（中文宋体/西文 Calibri）
style = doc.styles['Normal']
style.font.name = 'Calibri'
style.font.size = Pt(11)

def title(text):
    p = doc.add_heading(text, level=0)
    return p

def section(text):
    doc.add_heading(text, level=1)

def para(text, bold=False):
    p = doc.add_paragraph()
    run = p.add_run(text)
    run.bold = bold
    return p

title('数据结构章节测验（docx 导入测试）')
para('本文件用于验证题库文档导入解析：包含单选、多选、判断、填空、简答五种题型。', bold=False)

section('一、单选题')
para('1. 顺序表中访问第 i 个元素的时间复杂度为？')
para('A. O(1)')
para('B. O(n)')
para('C. O(n²)')
para('D. O(log n)')
para('答案：A')
para('解析：顺序表支持随机访问，可直接计算出元素地址。')

para('2. 单链表不具有的特点是？')
para('A. 插入和删除不需要移动元素')
para('B. 所需存储空间与数据元素个数成正比')
para('C. 可以随机访问任意位置的元素')
para('D. 结点由数据域和指针域组成')
para('答案：C')

section('二、多项选择题')
para('3. 以下属于线性结构的有？')
para('A. 栈')
para('B. 队列')
para('C. 二叉树')
para('D. 串')
para('答案：ABD')

section('三、判断题')
para('4. 栈的特点是后进先出（LIFO）。')
para('答案：对')
para('5. 循环队列中，元素个数就等于尾指针减头指针。')
para('答案：错')

section('四、填空题')
para('6. 循环队列中，判断队列为空的条件是______。')
para('答案：front == rear')

section('五、简答题')
para('7. 请简述线性表顺序存储与链式存储的主要区别。')
para('参考答案：顺序存储支持随机访问，但插入删除需要移动元素；链式存储不支持随机访问，但插入删除只需修改指针。')

out = r'D:/Claude_Code/智课系统V2/docs/测试文件目录/题目导入测试样例.docx'
doc.save(out)
print('saved:', out)
