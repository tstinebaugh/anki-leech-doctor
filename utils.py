import re

def format_notes_for_anki(notes_text: str) -> str:
    """
    Converts markdown notes into clean HTML suitable for Anki flashcard rendering.
    Preserves existing HTML if present while formatting markdown syntax (###, **, *, ---, \n).
    """
    if not notes_text or not str(notes_text).strip():
        return ""

    text = str(notes_text).strip()

    # Already-formatted HTML (e.g. notes saved from a draft card) passes through
    # unchanged instead of being wrapped in a second <p>.
    if re.match(r"^\s*<(p|h[1-6]|div|ul|ol|hr|br|b|strong)\b", text, re.IGNORECASE) and not re.search(
        r"(\*\*|^#{1,6}\s|^[-*•]\s)", text, re.MULTILINE
    ):
        return text
    
    # Split into sections by double newline
    blocks = re.split(r"\n\s*\n", text)
    html_blocks = []

    for block in blocks:
        block = block.strip()
        if not block:
            continue

        # Horizontal Rule
        if re.match(r"^(?:---|\*\*\*|___)$", block):
            html_blocks.append("<hr>")
            continue

        lines = block.split("\n")
        current_p_lines = []

        for line in lines:
            line_str = line.strip()
            if not line_str:
                continue

            # Header line: #, ##, ###, ####
            h_match = re.match(r"^(#{1,6})\s+(.*)$", line_str)
            if h_match:
                if current_p_lines:
                    html_blocks.append("<p>" + "<br>".join(current_p_lines) + "</p>")
                    current_p_lines = []
                h_lvl = len(h_match.group(1))
                h_txt = h_match.group(2).strip()
                h_txt = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", h_txt)
                h_txt = re.sub(r"__(.+?)__", r"<b>\1</b>", h_txt)
                h_txt = re.sub(r"(?<!\*)\*([^*]+?)\*(?!\*)", r"<i>\1</i>", h_txt)
                html_blocks.append(f"<h{h_lvl}>{h_txt}</h{h_lvl}>")
                continue

            # Horizontal rule inside block
            if re.match(r"^(?:---|\*\*\*|___)$", line_str):
                if current_p_lines:
                    html_blocks.append("<p>" + "<br>".join(current_p_lines) + "</p>")
                    current_p_lines = []
                html_blocks.append("<hr>")
                continue

            # List item
            li_match = re.match(r"^[-*•]\s+(.*)$", line_str)
            if li_match:
                li_txt = li_match.group(1).strip()
                li_txt = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", li_txt)
                li_txt = re.sub(r"__(.+?)__", r"<b>\1</b>", li_txt)
                li_txt = re.sub(r"(?<!\*)\*([^*]+?)\*(?!\*)", r"<i>\1</i>", li_txt)
                li_txt = re.sub(r"`([^`]+?)`", r"<code>\1</code>", li_txt)
                current_p_lines.append(f"• {li_txt}")
                continue

            # Inline bold: **bold** or __bold__
            line_str = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", line_str)
            line_str = re.sub(r"__(.+?)__", r"<b>\1</b>", line_str)
            # Inline italic: *italic* or _italic_
            line_str = re.sub(r"(?<!\*)\*([^*]+?)\*(?!\*)", r"<i>\1</i>", line_str)
            # Inline code: `code`
            line_str = re.sub(r"`([^`]+?)`", r"<code>\1</code>", line_str)
            
            current_p_lines.append(line_str)

        if current_p_lines:
            html_blocks.append("<p>" + "<br>".join(current_p_lines) + "</p>")

    return "".join(html_blocks)
