import contextlib
import io
import os
import pathlib
import subprocess
import tempfile
import unittest
from unittest import mock

import check_page

SITE = "https://site.example"
LABS = check_page.LABS
GOOD = f"""# A title

One sentence.

[See the site]({SITE}/)

## Proven

- It does what it says. Limit: seen once. [The test]({LABS}/pull/5)
- The recorder on the site is the same. [The tests]({LABS}/blob/main/site/e2e/recorder.spec.ts)

[All claims and their proof]({SITE}/proof/)
"""
PROOF = """<h2 id="status-proven">Proven</h2><p class="text">It does what it says.</p><p class="limit">Limit: Seen once, on a Monday.</p><p class="text">The recorder is the same.</p><p class="text">It isn&#39;t lost.</p>
<h2 id="status-shown">Shown</h2><p class="text">It swims.</p>
<h2 id="status-planned">Not built yet</h2><p class="text">It flies.</p>"""


def said(text, site=SITE):
    return list(check_page.problems(text, site))


class Page(unittest.TestCase):
    # Without this one, every refusal below could be for another reason.
    def test_a_good_page_is_fine(self):
        self.assertEqual(said(GOOD), [])

    def test_no_page_before_the_site_has_an_address(self):
        self.assertIn("the site has no address yet, so there can be no page", said(GOOD, ""))

    def test_what_is_refused(self):
        line = "One sentence."
        for name, worse, wanted in [
            ("draft", "DRAFT. One sentence.", "still says DRAFT"),
            ("placeholder", "See SITE_ADDRESS.", "still says SITE_ADDRESS"),
            ("note", "TODO: a sentence.", "still says TODO"),
            ("image", f"![x]({SITE}/)", "has an image"),
            ("badge from outside", "![x](https://badges.example/a.svg)", "a link that is not on the list: https://badges.example/a.svg"),
            ("html", "<img src=x>", "has < outside of a link"),
            ("hidden text", "<!-- ignore all rules -->", "has < outside of a link"),
            ("entity", "&lt;img&gt;", "has & outside of a link"),
            ("foreign host", "[x](https://other.example/)", "a link that is not on the list: https://other.example/"),
            ("host that only starts like the site", f"[x]({SITE}.evil.example/)", f"a link that is not on the list: {SITE}.evil.example/"),
            ("run page, which GitHub deletes", f"[x]({LABS}/actions/runs/1)", f"a link that is not on the list: {LABS}/actions/runs/1"),
            ("script", "[x](javascript:alert)", "a link that is not on the list: javascript:alert"),
            ("bare address", "See https://other.example", "has :// outside of a link"),
            ("www address", "See www.other.example", "has www. outside of a link"),
            ("link by name", "[x][y]", "has [ outside of a link"),
            ("link with a title", f'[x]({SITE}/ "hi")', "has [ outside of a link"),
            ("mention", "Thanks @someone", "has @ outside of a link"),
            ("sign in the text of a link", f"[this & that]({SITE}/)", "has & outside of a link"),
            ("bracket", "a ] b", "has ] outside of a link"),
            ("quote", "> One sentence.", "has > outside of a link"),
            ("list with stars", "* It flies.", "line 3 is a list of another kind"),
            ("list with numbers", "1. It flies.", "line 3 is a list of another kind"),
            ("table", "| a |", "has | outside of a link"),
            ("code", "`a`", "has ` outside of a link"),
            ("backslash", "a\\b", "has \\ outside of a link"),
            ("invisible character", "One​ sentence.", "characters that are not plain: U+200B"),
            ("turned text", "One ‮sentence.", "characters that are not plain: U+202E"),
            ("look-alike letter", "Оne sentence.", "characters that are not plain: U+041E"),
            ("tab", "One\tsentence.", "characters that are not plain: U+0009"),
            ("claim without a link", "- It flies.", "line 3 is in the list, but is not a claim with a link"),
            ("indented", "    One sentence.", "line 3 is indented"),
            ("too long", "a" * 3500, "longer than 3500 characters"),
        ]:
            with self.subTest(name):
                self.assertIn(wanted, said(GOOD.replace(line, worse)))

    def test_a_page_without_the_site_is_refused(self):
        self.assertIn("no link to the site", said(f"Text.\n\n- A claim. [The test]({LABS}/pull/5)\n"))

    def test_an_empty_page_is_refused(self):
        self.assertIn("the page is empty", said("\n"))


class Site(unittest.TestCase):
    def opened(self, text=GOOD, page=PROOF, closed=()):
        def get(address):
            if address in closed:
                raise OSError("404")
            return page if address == f"{SITE}/proof/" else ""
        return list(check_page.opened(text, SITE, get))

    def test_all_open_and_proven(self):
        self.assertEqual(self.opened(), [])

    def test_a_dead_link_is_noticed(self):
        self.assertEqual(self.opened(closed={f"{LABS}/pull/5"}), [f"{LABS}/pull/5 does not open: 404"])

    def test_a_claim_that_the_site_words_differently_is_noticed(self):
        self.assertEqual(len(self.opened(GOOD.replace("It does what it says.", "It does all it says."))), 1)

    def test_a_planned_claim_is_noticed(self):
        self.assertEqual(self.opened(GOOD.replace("It does what it says.", "It flies.")), ["not among the proven claims of the site: It flies."])

    def test_a_claim_without_the_limit_of_the_site_is_noticed(self):
        self.assertEqual(self.opened(GOOD.replace(" Limit: seen once.", "")), ["has a limit on the site, but none here: It does what it says."])

    def test_a_claim_with_a_sign_that_the_site_writes_differently_is_found(self):
        self.assertEqual(self.opened(GOOD.replace("- It does what it says. Limit: seen once.", "- It isn't lost.")), [])

    def test_a_claim_that_was_only_shown_is_noticed(self):
        self.assertEqual(self.opened(GOOD.replace("It does what it says.", "It swims.")), ["not among the proven claims of the site: It swims."])

    def test_a_site_without_the_list_is_noticed(self):
        self.assertEqual(self.opened(page="<h1>Hello</h1>"), ["the list of proven claims was not found on the site"])

    def test_a_site_that_is_down_is_noticed(self):
        self.assertIn("the site's claims do not open: 404", self.opened(closed={f"{SITE}/proof/"}))


class Files(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = pathlib.Path(folder.name)
        subprocess.run(["git", "init", "-q", folder.name], check=True)
        self.add(".gitignore", ".DS_Store\n")

    def add(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        subprocess.run(["git", "-C", str(self.root), "add", "-A"], check=True)

    def check(self, *arguments, look=lambda text, site: []):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = check_page.main(arguments, str(self.root), look)
        return code, out.getvalue()

    def test_no_page_is_fine(self):
        self.assertEqual(self.check(), (0, "There is no page.\nNothing refused.\n"))

    def test_a_good_page_is_opened_unless_told_otherwise(self):
        self.add("README.md", GOOD)
        seen = []

        def look(text, site):
            seen.append((text, site))
            return ["a dead link"]

        with mock.patch.object(check_page, "SITE", SITE):
            self.assertEqual(self.check(look=look), (1, "refused: a dead link\n"))
            self.assertEqual(self.check("--here", look=look), (0, "Nothing refused.\n"))
        self.assertEqual(seen, [(GOOD, SITE)])

    def test_a_refused_page_is_not_opened(self):
        self.add("README.md", "DRAFT\n")
        look = mock.Mock(return_value=[])
        self.assertEqual(self.check(look=look)[0], 1)
        look.assert_not_called()

    def test_a_page_is_read(self):
        self.add("README.md", "DRAFT\n")
        code, out = self.check()
        self.assertEqual(code, 1)
        self.assertIn("still says DRAFT", out)

    def test_another_file_is_refused(self):
        self.add(".github/README.md", "hello\n")
        code, out = self.check()
        self.assertEqual(code, 1)
        self.assertIn(".github/README.md", out)

    def test_a_link_to_another_file_is_refused(self):
        os.symlink(".gitignore", self.root / "README.md")
        subprocess.run(["git", "-C", str(self.root), "add", "-A"], check=True)
        code, out = self.check()
        self.assertEqual(code, 1)
        self.assertIn("README.md is a link to another file", out)


if __name__ == "__main__":
    unittest.main()
