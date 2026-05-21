import re, os

text = '桌面上找到一个文本文件：`C:\\Users\\ExampleUser\\Desktop\\example.txt`（约 13KB），已作为附件处理，将通过邮件发送给你。'
print('text:', repr(text))

# Test first regex (backtick-quoted)
for m in re.finditer(r"""([`'"])([^`'"]+\.[a-zA-Z0-9]{2,})\1""", text):
    p = m.group(2)
    print('Match 1 (quoted):', repr(p), 'exists:', os.path.isfile(p))

# Test second regex (raw Windows path)
for m in re.finditer(r"""([a-zA-Z]:\\[^\s,;)\]}'`"]+\.?[a-zA-Z0-9]{0,4})""", text):
    p = m.group(1).strip("`'\" ")
    print('Match 2 (raw):', repr(p), 'exists:', os.path.isfile(p))

# Test if file actually exists
test_path = 'C:\\Users\\ExampleUser\\Desktop\\example.txt'
print('Direct isfile check:', os.path.isfile(test_path))
print('Normpath:', os.path.normpath(test_path))
print('Exists:', os.path.exists(test_path))
