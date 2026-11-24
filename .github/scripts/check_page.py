#!/usr/bin/env python3
"""Checks the profile page, README.md.

  check_page.py          everything: what can be seen in the files, every link, and the claims against the list on the
                         site. CI runs this on every pull request
  check_page.py --here   only what can be seen in the files, without the network

A page is refused as long as SITE is empty, so nothing can be shown before the site has an address.
No page at all is fine: it can be taken away again.
"""

import html
import pathlib
import re
import subprocess
import sys
import urllib.request

SITE = ""  # for example "https://example.org", without a slash at the end

LABS = "https://github.com/oplf-svg/cloud-labs"
LINKS = {
    f"{LABS}/blob/main/.github/workflows/sign-in.yml",
    f"{LABS}/blob/main/bootstrap/scripts/check_sign_in.py",
    f"{LABS}/pull/5",
    f"{LABS}/blob/main/.github/scripts/blocked_terms.py",
    f"{LABS}/blob/main/site/e2e/recorder.spec.ts",
}
FILES = {".gitignore", "README.md", ".github/workflows/ci.yml", ".github/scripts/check_page.py", ".github/scripts/test_check_page.py"}
LINK = re.compile(r"\[([^\[\]]+)\]\(([^()\s]+)\)")
CLAIM = re.compile(r"^- (.+?\.)( Limit: .+)? \[[^\[\]]+\]\([^()\s]+\)$")
LONGEST = 3500


def problems(text, site):
    """Says what is wrong with a page."""
    if not site:
        yield "the site has no address yet, so there can be no page"
    if not text.strip():
        yield "the page is empty"
    if len(text) > LONGEST:
        yield f"longer than {LONGEST} characters"
    if odd := sorted({f"U+{ord(one):04X}" for one in text if one != "\n" and not " " <= one <= "~"}):
        yield f"characters that are not plain: {', '.join(odd)}"
    for word in ("DRAFT", "SITE_ADDRESS", "TODO"):
        if word in text:
            yield f"still says {word}"
    addresses = [address for _, address in LINK.findall(text)]
    for address in addresses:
        if not (address in LINKS or site and address in (f"{site}/", f"{site}/proof/")):
            yield f"a link that is not on the list: {address}"
    if site and not {f"{site}/", f"{site}/proof/"} & set(addresses):
        yield "no link to the site"
    # What is left without its links has to be plain text: no image, HTML, table, code, mention or bare address.
    if "![" in text:
        yield "has an image"
    rest = LINK.sub(r"\1", text)
    for sign in ("[", "]", "<", ">", "|", "`", "&", "@", "\\", "://", "www."):
        if sign in rest:
            yield f"has {sign} outside of a link"
    for number, line in enumerate(text.split("\n"), 1):
        if line.startswith("- ") and not CLAIM.match(line):
            yield f"line {number} is in the list, but is not a claim with a link"
        if re.match(r"([*+]|\d+[.)])\s", line):
            yield f"line {number} is a list of another kind"
        if re.match(r"\s+\S", line):
            yield f"line {number} is indented"


def claims(text):
    """Every claim of the page, and whether it names a limit."""
    return [(found.group(1), bool(found.group(2))) for found in map(CLAIM.match, text.split("\n")) if found]


def not_proven(text, page):
    """Says which claims are not, word for word, among the proven ones of the site's page, or leave out that they have a limit."""
    start = page.find('id="status-proven"')
    if start < 0:
        yield "the list of proven claims was not found on the site"
        return
    # Up to the next group, whatever it is called: what is only shown or rehearsed is not proven.
    end = page.find('id="status-', start + 1)
    parts = page[start : end if end > start else None].split('<p class="text">')[1:]
    limited = {html.unescape(part.split("</p>")[0]): '<p class="limit">' in part for part in parts}
    for one, limit in claims(text):
        # Here the reader does not see the recorder, so the page says where it is.
        words = one.replace("The recorder on the site ", "The recorder ")
        if words not in limited:
            yield f"not among the proven claims of the site: {one}"
        elif limited[words] and not limit:
            yield f"has a limit on the site, but none here: {one}"


def fetch(address):
    with urllib.request.urlopen(urllib.request.Request(address, headers={"User-Agent": "page-check"}), timeout=30) as answer:
        return answer.read().decode("utf-8", errors="replace")


def opened(text, site, get=fetch):
    """Opens every link. Says what does not open, and what the site does not say."""
    for address in sorted({address for _, address in LINK.findall(text)}):
        try:
            get(address)
        except OSError as problem:
            yield f"{address} does not open: {problem}"
    try:
        yield from not_proven(text, get(f"{site}/proof/"))
    except OSError as problem:
        yield f"the site's claims do not open: {problem}"


def main(arguments, root=".", look=opened):
    listed = subprocess.run(["git", "-C", root, "ls-files", "-z"], check=True, capture_output=True, text=True).stdout
    found = [f"a file that does not belong here: {name}" for name in listed.split("\0") if name and name not in FILES]
    page = pathlib.Path(root, "README.md")
    if page.is_symlink():
        found.append("README.md is a link to another file")
    elif page.exists():
        text = page.read_text(encoding="utf-8", errors="replace")
        found += problems(text, SITE)
        # A page that is refused anyway is not opened: its links may lead anywhere.
        if "--here" not in arguments and not found:
            found += look(text, SITE)
    else:
        print("There is no page.")
    for one in found:
        print(f"refused: {one}")
    if not found:
        print("Nothing refused.")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
