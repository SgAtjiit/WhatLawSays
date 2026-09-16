"""Every Streamlit page must actually load.

The Contract Review page once died with a SyntaxError before rendering anything:
Streamlit's "magic" wraps bare expression statements in st.write, and its AST
pass could not parse a multi-line ternary. The suite passed 191 tests while the
feature was unreachable, because nothing in it ever executed a page.
"""

import pathlib

import pytest

PAGES = [
    "frontend/app.py",
    "frontend/pages/1_\u2696\ufe0f_Scenario_Analysis.py",
    "frontend/pages/2_\U0001f4c4_Contract_Review.py",
]


@pytest.mark.parametrize("page", PAGES)
def test_every_streamlit_page_loads(page):
    from streamlit.testing.v1 import AppTest

    # AppTest resolves a relative path against the calling file, which is this
    # test, not the repo root.
    root = pathlib.Path(__file__).resolve().parent.parent
    app = AppTest.from_file(str(root / page), default_timeout=120).run()
    assert not app.exception, [e.value for e in app.exception]
