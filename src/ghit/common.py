import pygit2 as git
from .stack import *
from .gitools import *
from .styling import *
from .gh import initGH, GH
from .args import Args

def connect(args: Args) -> tuple[git.Repository, Stack, GH]:
    repo = git.Repository(args.repository)
    if repo.is_empty:
        return repo, None, None
    stack = open_stack(args.stack)
    if not stack:
        stack = Stack()
        current = get_current_branch(repo)
        stack.add_child([], current.branch_name)
    return repo, stack, initGH(repo, stack, args.offline)



def update_upstream(repo: git.Repository, origin: git.Remote, branch: git.Branch):
    full_name = branch.resolve().name
    mrc = MyRemoteCallback()
    origin.push([full_name], callbacks=mrc)
    if not mrc.message:
        # TODO: weak logic?
        branch_ref: str = origin.get_refspec(0).transform(full_name)
        branch.upstream = repo.branches.remote[branch_ref.removeprefix("refs/remotes/")]
        print(
            "Pushed ",
            emphasis(branch.branch_name),
            " to remote ",
            emphasis(origin.url),
            " and set upstream to ",
            emphasis(branch.upstream.branch_name),
            ".",
            sep="",
        )


def sync_branch(args: Args, repo: git.Repository, gh: GH, origin: git.Remote, record: StackRecord):
    branch = repo.branches[record.branch_name]
    if not branch.upstream:
        update_upstream(repo, origin, branch)
    prs = gh.getPRs(record.branch_name)
    if prs and not all(p.closed for p in prs):
        for pr in prs:
            gh.comment(pr)
    else:
        gh.create_pr(record.parent.branch_name, record.branch_name, args.title, args.draft)
