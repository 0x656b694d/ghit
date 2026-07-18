from types import SimpleNamespace

from ghit.gh import COMMENT_BEGIN, COMMENT_END, COMMENT_FIRST_LINE, GH, _find_stack_comment, _patch_body
from ghit.stack import parse


def _make_gh(stack, prs) -> GH:
    gh = GH.__new__(GH)
    gh.stack = stack
    gh._GH__prs = prs
    return gh


def test_find_stack_comment():
    assert _find_stack_comment('body') is None
    body = ['body', COMMENT_BEGIN, COMMENT_FIRST_LINE, COMMENT_END]
    assert _find_stack_comment('\n'.join(body)) == (5, 105)


def test_patch_body():
    assert _patch_body('body', 'comment') == 'body\ncomment'
    body = ['body', COMMENT_BEGIN, COMMENT_FIRST_LINE, COMMENT_END]
    assert _patch_body('\n'.join(body), 'comment') == 'body\ncomment'


def test_make_stack_comment_skips_sibling_subtrees():
    stack = parse(['main', '.br-1', '..br-2', '...br-3', '..br-4', '...br-5'])
    gh = _make_gh(
        stack,
        {
            'br-1': [SimpleNamespace(number=1)],
            'br-2': [SimpleNamespace(number=2)],
            'br-3': [SimpleNamespace(number=3)],
            'br-4': [SimpleNamespace(number=4)],
            'br-5': [SimpleNamespace(number=5)],
        },
    )
    assert gh._make_stack_comment(4, 'br-4') == '\n'.join(
        [
            COMMENT_BEGIN,
            COMMENT_FIRST_LINE,
            '',
            '* [main](../tree/main)',
            '  * **PR #1**',
            '    * **PR #4** 👈',
            '      * **PR #5**',
            COMMENT_END,
        ]
    )


def test_make_stack_comment_unknown_branch_keeps_all():
    stack = parse(['main', '.br-1', '..br-2'])
    gh = _make_gh(stack, {'br-1': [SimpleNamespace(number=1)]})
    assert gh._make_stack_comment(99, 'not-in-stack') == '\n'.join(
        [
            COMMENT_BEGIN,
            COMMENT_FIRST_LINE,
            '',
            '* [main](../tree/main)',
            '  * **PR #1**',
            '    * [br-2](../tree/br-2)',
            COMMENT_END,
        ]
    )
