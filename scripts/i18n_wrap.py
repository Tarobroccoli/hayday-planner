"""One-off helper: wrap every Thai phrase in JS source with t("...") so the UI can switch language.

Inside a template literal the phrase becomes ${t("phrase")}; inside a plain '...' or "..." string the
whole literal becomes t("phrase") when it is exactly the phrase, otherwise it is turned into a template
literal with ${t(...)} parts. Prints every phrase found (the keys the English dictionary needs).

Usage: i18n_wrap.py <file> [--script-only]   (--script-only: only touch the last <script> block of an HTML file)
"""
import re, sys

THAI = re.compile(r"[฀-๿][^\"'`<>${}\\]*")


def lex(src):
    """Yield (start, end, kind, quote) for every string-ish segment: kind 'tpl' (template text) or 'str'."""
    i, n, stack, out = 0, len(src), [], []   # stack of "tpl" / "{" for nesting inside ${ }
    prev = "("                               # last significant char, for regex detection
    while i < n:
        c = src[i]
        in_tpl = stack and stack[-1] == "tpl"
        if in_tpl:
            j = i
            while j < n and src[j] != "`" and not (src[j] == "$" and src[j + 1:j + 2] == "{"):
                j += 2 if src[j] == "\\" else 1
            out.append((i, j, "tpl", "`"))
            if j < n and src[j] == "`":
                stack.pop(); i = j + 1; prev = "`"
            else:
                stack.append("{"); i = j + 2; prev = "{"
            continue
        if c == "/" and src[i + 1:i + 2] == "/":
            i = src.index("\n", i) if "\n" in src[i:] else n; continue
        if c == "/" and src[i + 1:i + 2] == "*":
            i = src.index("*/", i) + 2; continue
        if c in "\"'":
            j = i + 1
            while src[j] != c:
                j += 2 if src[j] == "\\" else 1
            out.append((i + 1, j, "str", c)); i = j + 1; prev = c; continue
        if c == "`":
            stack.append("tpl"); i += 1; continue
        if c == "/" and prev in "(,=:[!&|?{};+-*%<>~^":
            j = i + 1; cls = False
            while src[j] != "/" or cls:
                if src[j] == "\\": j += 1
                elif src[j] == "[": cls = True
                elif src[j] == "]": cls = False
                j += 1
            i = j + 1; prev = "/"; continue
        if c == "{" and stack:
            stack.append("{")
        elif c == "}" and stack and stack[-1] == "{":
            stack.pop()
            if stack and stack[-1] == "tpl":
                i += 1; continue
        if not c.isspace():
            prev = c
        i += 1
    return out


def wrap(src):
    edits, phrases = [], []
    for s, e, kind, q in lex(src):
        body = src[s:e]
        ms = list(THAI.finditer(body))
        if not ms:
            continue
        for m in ms:
            if m.group(0) not in phrases: phrases.append(m.group(0))
        sub = lambda b: THAI.sub(lambda m: '${t("' + m.group(0) + '")}', b)
        if kind == "tpl":
            edits.append((s, e, sub(body)))
        elif len(ms) == 1 and ms[0].group(0) == body:
            edits.append((s - 1, e + 1, 't("' + body + '")'))
        else:
            edits.append((s - 1, e + 1, "`" + sub(body) + "`"))
    for s, e, new in sorted(edits, reverse=True):
        src = src[:s] + new + src[e:]
    return src, phrases


def main():
    path = sys.argv[1]
    src = open(path).read()
    if "--script-only" in sys.argv:
        a = src.rindex("<script>") + len("<script>"); b = src.rindex("</script>")
        body, phrases = wrap(src[a:b]); src = src[:a] + body + src[b:]
    else:
        src, phrases = wrap(src)
    open(path, "w").write(src)
    for p in phrases: print(p)


if __name__ == "__main__":
    main()
