from .common import *
from .styling import *
import pygit2 as git


def _check_stack(
    repo: git.Repository, stack: Stack
) -> Iterator[tuple[Stack, int]]:
    if repo.is_empty:
        return
    depth = 0
    for record in stack.rtraverse(False):
        if record.depth < depth:
            break
        parent = record.get_parent()
        parent_ref = repo.references.get(f"refs/heads/{parent.branch_name}")
        record_ref = repo.references.get(f"refs/heads/{record.branch_name}")
        if not record_ref:
            continue
        a, _ = repo.ahead_behind(parent_ref.target, record_ref.target)
        if a != 0:
            yield (record, a)
            depth = record.depth


def check(args: Args):
    repo, stack, _ = connect(args)
    for notsync in _check_stack(repo, stack):
        record, a = notsync
        print(
            warning("🗶"),
            emphasis(record.get_parent().branch_name),
            warning("is ahead of"),
            emphasis(record.branch_name),
            warning("with:"),
        )
        parent_ref = repo.references.get(f"refs/heads/{record.get_parent().branch_name}")

        for commit in last_commits(repo, parent_ref.target, a):
            print(inactive(f"\t[{commit.short_id}] {commit.message.splitlines()[0]}"))

        print(f"  Run `git rebase -i {record.get_parent().branch_name} {record.branch_name}`.")

    if not notsync:
        print(good("🗸 The stack is in shape."))


def restack(args: Args):
    repo, stack, _ = connect(args)

    for _ in _check_stack(repo, stack):
        return

    for record in stack.traverse(False):
        record_name = record.branch_name
        parent_name = record.get_parent().branch_name
        parent_ref = repo.references.get(f"refs/heads/{parent_name}")
        if parent_ref is None:
            continue
        record_ref = repo.references.get(f"refs/heads/{record_name}")
        if record_ref is None:
            print(
                warning("No local branch"),
                emphasis(record_name),
                warning("found"),
            )
            continue
        a, _ = repo.ahead_behind(parent_ref.target, record_ref.target)
        if a == 0:
            print(
                good("🗸"),
                emphasis(record_name),
                good("is already on"),
                emphasis(parent_name),
            )
            continue

        print()
        print(
            warning("🗶"),
            emphasis(parent_name),
            warning("is ahead of"),
            emphasis(record_name),
            warning("with:"),
        )

        for commit in last_commits(repo, parent_ref.target, a):
            print(inactive(f"\t[{commit.short_id}] {commit.message.splitlines()[0]}"))

        print(f"  Run `git rebase -i {parent_name} {record_name}`.")


def stack_sync(args: Args):
    repo, stack, gh = connect(args)
    if repo.is_empty:
        return
    origin = repo.remotes["origin"]
    if not origin:
        print(warning("No origin found for the repository."))
        return

    mrc = MyRemoteCallback()
    print("Fetching from", origin.url)
    progress = origin.fetch(callbacks=mrc)
    print("\treceived objects:", progress.received_objects)
    print("\ttotal deltas:", progress.total_deltas)
    print("\ttotal objects:", progress.total_objects)

    for record in stack.traverse(False):
        sync_branch(repo, gh, origin, record)

def dump(args:Args):
    _, stack, _ = connect(args)
    lines = []
    stack.dumps(lines)
    print("\n".join(lines))
