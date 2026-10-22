+++
title = '我的第一篇学习笔记'
date = 2026-10-21T21:00:00+08:00
draft = true
categories = ['学习笔记']
tags = ['Hugo', 'Markdown']
summary = '通过一篇中文学习笔记，验证 Hugo 和 PaperMod 对 Markdown 标题、段落、列表及 Python 代码块的展示。'
+++

# 从记录开始学习

这是我的第一篇学习笔记，也是这个个人学术博客的第一篇测试文章。我希望用简洁的文字记录学习过程，把零散的知识逐步整理成可以回顾和复用的笔记。

## 用 Markdown 整理内容

Markdown 可以用纯文本表达文章结构。写作时，我可以专注于内容，再由 Hugo 将源文件生成网页，交给 PaperMod 负责页面排版。

每次学习后，我计划记录以下内容：

- 今天学习了什么，以及它要解决的问题。
- 实践中遇到的困难和解决方法。
- 值得继续阅读的资料与下一步计划。

## 一个简单的 Python 示例

下面的代码计算三次学习时长的平均值。代码块标注为 `python`，用于检查网页中的语法高亮与缩进是否正常。

```python
study_minutes = [30, 45, 60]
average_minutes = sum(study_minutes) / len(study_minutes)

for day, minutes in enumerate(study_minutes, start=1):
    print(f"第 {day} 天学习了 {minutes} 分钟")

print(f"平均每天学习 {average_minutes:.1f} 分钟")
```

## 下一步

这篇文章先用于验证发布流程。之后，我会继续积累学习笔记、科研方法和文献阅读记录，让每一次学习都留下清晰的线索。
