"""Confluence formatting utilities."""

import re


def _inline_md_to_html(text: str) -> str:
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
    text = re.sub(r"`(.+?)`", r"<code>\1</code>", text)
    return re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)


def markdown_to_storage(md_text: str) -> str:
    """Convert markdown text to Confluence storage format (XHTML)."""
    lines = md_text.splitlines()
    out: list[str] = []
    i = 0
    list_stack: list[tuple[str, int]] = []

    def close_all_lists():
        while list_stack:
            out.append(f"</{list_stack.pop()[0]}>")

    def adjust_list(tag: str, indent: int):
        while list_stack and list_stack[-1][1] > indent:
            out.append(f"</{list_stack.pop()[0]}>")
        if list_stack and list_stack[-1][1] == indent and list_stack[-1][0] != tag:
            out.append(f"</{list_stack.pop()[0]}>")
        if not list_stack or list_stack[-1][1] < indent:
            out.append(f"<{tag}>")
            list_stack.append((tag, indent))

    while i < len(lines):
        line = lines[i]
        if re.match(r"^```", line):
            close_all_lists()
            lang = line[3:].strip()
            code_lines = []
            i += 1
            while i < len(lines) and not re.match(r"^```", lines[i]):
                code_lines.append(lines[i])
                i += 1
            lang_param = f'<ac:parameter ac:name="language">{lang}</ac:parameter>' if lang else ""
            out.append(f'<ac:structured-macro ac:name="code">{lang_param}<ac:plain-text-body><![CDATA[{chr(10).join(code_lines)}]]></ac:plain-text-body></ac:structured-macro>')
            i += 1
            continue
        hm = re.match(r"^(#{1,6})\s+(.+)", line)
        if hm:
            close_all_lists()
            out.append(f"<h{len(hm.group(1))}>{_inline_md_to_html(hm.group(2).strip())}</h{len(hm.group(1))}>")
            i += 1
            continue
        um = re.match(r"^(\s*)[-*•]\s+(.+)", line)
        if um:
            adjust_list("ul", len(um.group(1)))
            out.append(f"<li>{_inline_md_to_html(re.sub(r'^#{1,6}\s+', '', um.group(2).strip()))}</li>")
            i += 1
            continue
        om = re.match(r"^(\s*)\d+[.)]\s+(?:#{1,6}\s+)?(.+)", line)
        if om:
            adjust_list("ol", len(om.group(1)))
            out.append(f"<li>{_inline_md_to_html(om.group(2).strip())}</li>")
            i += 1
            continue
        if not line.strip():
            close_all_lists()
            i += 1
            continue
        close_all_lists()
        out.append(f"<p>{_inline_md_to_html(line.strip())}</p>")
        i += 1

    close_all_lists()
    return "\n".join(out)
