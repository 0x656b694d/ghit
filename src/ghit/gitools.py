from collections.abc import Iterator
from pathlib import Path

import pygit2 as git

from . import styling as s
from . import terminal
from .stack import Stack


def get_git_ssh_credentials() -> git.credentials.KeypairFromAgent:
    return git.KeypairFromAgent('git')


class MyRemoteCallback(git.RemoteCallbacks):
    def __init__(self, credentials=None, certificate=None):
        super().__init__(credentials or get_git_ssh_credentials(), certificate)
        self.message = ''

    def push_update_reference(self, refname, message):
        self.message = message
        self.refname = refname


def common_gitdir(repo: git.Repository) -> Path:
    """Resolve the git directory shared by all worktrees of the repository."""
    gitdir = Path(repo.path)
    commondir = gitdir / 'commondir'
    if commondir.is_file():
        return (gitdir / commondir.read_text().strip()).resolve()
    return gitdir


GHIT_BASE_REF_PREFIX = 'refs/ghit/base/'


def base_ref_name(branch_name: str) -> str:
    return GHIT_BASE_REF_PREFIX + branch_name


def get_base(repo: git.Repository, branch_name: str) -> git.Oid | None:
    """Return the recorded base of the branch: the parent tip its commits sit on."""
    ref = repo.references.get(base_ref_name(branch_name))
    return ref.target if ref else None


def set_base(repo: git.Repository, branch_name: str, target: git.Oid) -> None:
    repo.references.create(base_ref_name(branch_name), target, force=True)


def _is_ancestor_or_same(repo: git.Repository, ancestor: git.Oid, descendant: git.Oid) -> bool:
    return ancestor == descendant or repo.descendant_of(descendant, ancestor)


def resolve_base(repo: git.Repository, branch_name: str, parent_name: str) -> git.Oid | None:
    """Return the base of the branch, recovering and recording it when missing or stale.

    The recorded base is stale when it is no longer an ancestor of the branch
    (the branch was reset), or when the merge base with the parent is newer
    (the branch was manually rebased onto a newer parent state).
    """
    branch = repo.branches.get(branch_name)
    parent = repo.branches.get(parent_name)
    if not branch or not parent:
        return None
    stored = get_base(repo, branch_name)
    stored_valid = stored is not None and _is_ancestor_or_same(repo, stored, branch.target)
    merge_base = repo.merge_base(parent.target, branch.target)
    if stored_valid and (merge_base is None or not repo.descendant_of(merge_base, stored)):
        return stored
    if merge_base is None:
        terminal.verbose(
            s.inactive(f'Branches {branch_name} and {parent_name} have no common history, cannot find the base.')
        )
        return None
    if stored is None:
        terminal.verbose(
            s.inactive(
                f'No recorded base of {branch_name}: took the merge base with {parent_name}, '
                f'[{repo[merge_base].short_id}].'
            )
        )
    elif not stored_valid:
        terminal.verbose(
            s.inactive(
                f'Recorded base of {branch_name}, [{repo[stored].short_id}], is not its ancestor anymore '
                f'(branch reset?): took the merge base with {parent_name}, [{repo[merge_base].short_id}].'
            )
        )
    else:
        terminal.verbose(
            s.inactive(
                f'{branch_name} already sits on a newer state of {parent_name} (rebased manually?): '
                f'moved its base from [{repo[stored].short_id}] to [{repo[merge_base].short_id}].'
            )
        )
    set_base(repo, branch_name, merge_base)
    return merge_base


def get_default_branch(repo: git.Repository) -> str:
    remote_head = repo.references['refs/remotes/origin/HEAD'].resolve().shorthand
    return remote_head.removeprefix('origin/')


def get_current_branch(repo: git.Repository) -> git.Branch:
    return repo.lookup_branch(repo.head.resolve().shorthand)


def last_commits(repo: git.Repository, target: git.Oid, n: int = 1) -> Iterator[git.Commit]:
    if n == 0:
        return
    for i, commit in enumerate(repo.walk(target), start=1):
        yield commit
        if i >= n:
            break


def print_branch_info(repo: git.Repository, record: Stack, branch: git.Branch) -> None:
    if not record.get_parent():
        return
    parent_branch = repo.branches[record.get_parent().branch_name]
    a, _ = repo.ahead_behind(parent_branch.target, branch.target)
    if a:
        terminal.stdout('This branch has fallen back behind ' + s.emphasis(record.get_parent().branch_name) + '.')
        terminal.stdout('You may want to restack to pick up the following commits:')
        for commit in last_commits(repo, parent_branch.target, a):
            terminal.stdout(s.inactive(f'\t[{commit.short_id}] ' + commit.message.splitlines()[0]))


def print_upstream_info(repo: git.Repository, branch: git.Branch) -> None:
    try:
        upstream = branch.upstream
    except KeyError:
        upstream = None
    if not upstream:
        terminal.stdout("The branch doesn't have an upstream.")
        return
    a, b = repo.ahead_behind(
        branch.target,
        upstream.target,
    )
    if a:
        terminal.stdout(
            'Following local commits are missing in upstream ' + s.emphasis(upstream.branch_name) + ':'
        )
        for commit in last_commits(repo, branch.target, a):
            terminal.stdout(s.inactive(f'\t[{commit.short_id}] {commit.message.splitlines()[0]}'))
    if b:
        terminal.stdout('Following upstream commits are missing in local ' + s.emphasis(branch.branch_name) + ':')
        for commit in last_commits(repo, upstream.target, b):
            terminal.stdout(s.inactive(f'\t[{commit.short_id}] {commit.message.splitlines()[0]}'))


def checkout(repo: git.Repository, record: Stack) -> None:
    branch_name = record.branch_name
    branch = repo.branches.get(branch_name) if branch_name else None
    if not branch:
        terminal.stdout(
            s.danger('Error:'),
            s.emphasis(branch_name or '<empty>'),
            s.danger('not found in local.'),
        )
        if branch_name is not None:
            remote = repo.branches.remote['origin/' + branch_name]
            if remote:
                terminal.stdout('There is though a remote branch ' + s.emphasis(remote.branch_name) + '.')
        return
    repo.checkout(branch)
    terminal.stdout(f'Checked-out {s.emphasis(branch.branch_name)}.')
    print_branch_info(repo, record, branch)
    print_upstream_info(repo, branch)


def insert(repo: git.Repository, branch_name: str, stack: Stack):
    branch = repo.branches.get(branch_name)
    if not branch:
        return
    best: Stack | None = None
    for record in stack.traverse():
        b = repo.branches.get(record.branch_name)
        if b and (b.target == branch.target or repo.descendant_of(branch.target, b.target)):
            best = record
    if best:
        best.add_child(branch_name, True, False)
