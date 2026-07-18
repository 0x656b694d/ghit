import pygit2 as git
import pytest

from ghit import terminal
from ghit.gitools import base_ref_name, get_base, resolve_base, set_base


def _commit(repo: git.Repository, ref: str, message: str, parents: list[git.Oid]) -> git.Oid:
    author = git.Signature('test', 'test@example.com')
    tree = repo.TreeBuilder().write()
    return repo.create_commit(ref, author, author, message, tree, parents)


@pytest.fixture
def repo(tmp_path) -> git.Repository:
    """A repository where br forked from main at commit A, and main moved ahead.

    A---C   (main)
     \
      B     (br)
    """
    repo = git.init_repository(tmp_path / 'repo', initial_head='main')
    a = _commit(repo, 'HEAD', 'A', [])
    repo.branches.local.create('br', repo[a])
    _commit(repo, 'refs/heads/br', 'B', [a])
    _commit(repo, 'refs/heads/main', 'C', [a])
    return repo


def _tip(repo: git.Repository, branch_name: str) -> git.Oid:
    return repo.branches[branch_name].target


def _commit_a(repo: git.Repository) -> git.Oid:
    return repo.merge_base(_tip(repo, 'main'), _tip(repo, 'br'))


def test_get_set_base(repo):
    assert get_base(repo, 'br') is None
    a = _commit_a(repo)
    set_base(repo, 'br', a)
    assert get_base(repo, 'br') == a
    assert repo.references[base_ref_name('br')].target == a


def test_resolve_base_backfills_from_merge_base(repo):
    a = _commit_a(repo)
    assert resolve_base(repo, 'br', 'main') == a
    assert get_base(repo, 'br') == a


def test_resolve_base_keeps_stored(repo):
    a = _commit_a(repo)
    set_base(repo, 'br', a)
    assert resolve_base(repo, 'br', 'main') == a


def test_resolve_base_recovers_after_reset(repo):
    # C is not an ancestor of br: as if br was reset elsewhere.
    set_base(repo, 'br', _tip(repo, 'main'))
    assert resolve_base(repo, 'br', 'main') == _commit_a(repo)


def test_resolve_base_follows_manual_rebase(repo):
    a = _commit_a(repo)
    set_base(repo, 'br', a)
    # Rebase br onto main by hand: B' on top of C.
    c = _tip(repo, 'main')
    b2 = _commit(repo, None, 'B2', [c])
    repo.references['refs/heads/br'].set_target(b2)
    assert resolve_base(repo, 'br', 'main') == c
    assert get_base(repo, 'br') == c


def test_resolve_base_missing_branch(repo):
    assert resolve_base(repo, 'nope', 'main') is None


def test_resolve_base_explains_backfill(repo, capsys):
    terminal.set_verbose(True)
    try:
        resolve_base(repo, 'br', 'main')
    finally:
        terminal.set_verbose(False)
    out = capsys.readouterr().out
    assert 'No recorded base of br' in out
    assert repo[_commit_a(repo)].short_id in out


def test_resolve_base_silent_without_verbose(repo, capsys):
    resolve_base(repo, 'br', 'main')
    assert capsys.readouterr().out == ''
