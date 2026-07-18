from pathlib import Path

import pygit2 as git
import pytest

from ghit.args import Args
from ghit.branch_commands import create
from ghit.common import ConnectionsCache, Context, check_record, stack_filename
from ghit.gitools import common_gitdir, get_base
from ghit.stack import parse
from ghit.top_commands import init


@pytest.fixture(autouse=True)
def fresh_context():
    ConnectionsCache._context = None
    yield
    ConnectionsCache._context = None


def _make_args(repository: str) -> Args:
    return Args(
        stack='',
        repository=repository,
        offline=True,
        title='',
        debug=False,
        verbose=False,
        draft=False,
        branch='',
    )


def _commit(repo: git.Repository) -> git.Oid:
    author = git.Signature('test', 'test@example.com')
    tree = repo.TreeBuilder().write()
    return repo.create_commit('HEAD', author, author, 'initial', tree, [])


@pytest.fixture
def repo(tmp_path) -> git.Repository:
    return git.init_repository(tmp_path / 'repo', initial_head='main')


def test_stack_filename_default(repo):
    assert stack_filename(repo) == Path(repo.path) / 'ghit' / 'stack'


def test_stack_filename_env(repo, monkeypatch):
    monkeypatch.setenv('GHIT_STACK', '/somewhere/else/stack')
    assert stack_filename(repo) == Path('/somewhere/else/stack')


def test_common_gitdir_worktree(repo, tmp_path):
    oid = _commit(repo)
    branch = repo.branches.local.create('wt', repo[oid])
    repo.add_worktree('wt', str(tmp_path / 'wt'), branch)

    wt_repo = git.Repository(str(tmp_path / 'wt'))
    assert Path(wt_repo.path) != Path(repo.path)
    assert common_gitdir(wt_repo) == Path(repo.path).resolve()
    assert stack_filename(wt_repo) == Path(repo.path).resolve() / 'ghit' / 'stack'


def test_init_creates_stack_in_gitdir(repo, tmp_path, monkeypatch):
    monkeypatch.delenv('GHIT_STACK', raising=False)
    _commit(repo)

    init(_make_args(str(tmp_path / 'repo')))

    stack_file = Path(repo.path) / 'ghit' / 'stack'
    assert stack_file.read_text() == 'main\n'
    assert not (tmp_path / 'repo' / '.ghit').exists()


def test_branch_create_records_base(repo, tmp_path, monkeypatch):
    monkeypatch.delenv('GHIT_STACK', raising=False)
    head = _commit(repo)

    args = _make_args(str(tmp_path / 'repo'))
    args.branch = 'feat'
    create(args)

    assert get_base(repo, 'feat') == head


def test_check_record_suggests_rebase_from_base(repo, capsys):
    author = git.Signature('test', 'test@example.com')
    tree = repo.TreeBuilder().write()
    a = repo.create_commit('HEAD', author, author, 'A', tree, [])
    repo.branches.local.create('br', repo[a])
    repo.create_commit('refs/heads/br', author, author, 'B', tree, [a])
    repo.create_commit('refs/heads/main', author, author, 'C', tree, [a])

    stack = parse(['main', '.br'])
    ctx = Context(repo=repo, stack=stack, gh=None, args=_make_args(str(repo.workdir)))
    record = stack.find('br')
    assert record is not None

    assert not check_record(ctx, record)
    out = capsys.readouterr().out
    assert 'git rebase -i --onto' in out
    assert repo[a].short_id in out
    assert get_base(repo, 'br') == a
