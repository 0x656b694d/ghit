import requests
import sys
from dataclasses import dataclass
import logging
from typing import TypeVar, Generic, Callable
from collections.abc import Iterator

T = TypeVar("T")

# region builder


def fields(*f: str) -> str:
    return " ".join(f)


def on(t: str, *f) -> str:
    return obj(f"... on {t}", *f)


def obj(name: str, *f: str) -> str:
    return name + "{ " + fields(*f) + " }"


query = obj


def func(name: str, args: dict[str, str], *f: str) -> str:
    extra = ", ".join(f"{k}: {v}" for k, v in args.items())
    return obj(f"{name}({extra})", *f)


def paged(name: str, args: dict[str, str], *f: str) -> str:
    return func(
        name,
        args,
        obj("pageInfo", "endCursor"),
        obj("edges", "cursor", obj("node", *f)),
    )


# endregion builder

# region query
FIRST_FEW = {"first": 10}

GQL_REACTION = fields("content", obj("user", "login", "name"))
GQL_AUTHOR = obj("author", "login", on("User", "name"))
GQL_COMMENT = fields(
    "id",
    "url",
    "body",
    "minimizedReason",
    GQL_AUTHOR,
    paged("reactions", FIRST_FEW, GQL_REACTION),
)
GQL_REVIEW_THREAD = fields(
    "path",
    "isResolved",
    "isOutdated",
    paged("comments", {"last": 1}, GQL_COMMENT),
)
GQL_REVIEW = fields("state", "url", GQL_AUTHOR)
GQL_COMMIT = obj("commit", paged("comments", {"last": 1}, GQL_COMMENT))
GQL_PR = fields(
    "number",
    "id",
    "title",
    GQL_AUTHOR,
    "baseRefName",
    "headRefName",
    "isDraft",
    "locked",
    "closed",
    "merged",
    "state",
    paged("comments", FIRST_FEW, GQL_COMMENT),
    paged("reviewThreads", FIRST_FEW, GQL_REVIEW_THREAD),
    paged("reviews", FIRST_FEW, GQL_REVIEW),
    paged("commits", FIRST_FEW, GQL_COMMIT),
)


def cursor_or_null(c: str | None) -> str:
    return f'"{c}"' if c else "null"


GQL_PRS_QUERY = lambda owner, repository, heads, after=None: query(
    "query search_prs",
    paged(
        "search",
        {
            **FIRST_FEW,
            "after": cursor_or_null(after),
            "type": "ISSUE",
            "query": f'"repo:{owner}/{repository} is:pr {heads}"',
        },
        on("PullRequest", GQL_PR),
    ),
)


def pr_details_query(detail: str, obj: str):
    return lambda owner, repository, pr_number, after=None: query(
        f"query pr_{detail}",
        func(
            "repository",
            {"owner": f'"{owner}"', "name": f'"{repository}"'},
            func(
                "pullRequest",
                {"number": pr_number},
                paged(detail, {**FIRST_FEW, "after": cursor_or_null(after)}, obj),
            ),
        ),
    )


GQL_PR_COMMENTS_QUERY = pr_details_query("comments", GQL_COMMENT)

GQL_PR_COMMENT_REACTIONS_QUERY = (
    lambda owner, repository, pr_number, comment_cursor=None, after=None: query(
        f"query pr_comments_reactions",
        func(
            "repository",
            {"owner": f'"{owner}"', "name": f'"{repository}"'},
            func(
                "pullRequest",
                {"number": pr_number},
                paged(
                    "comments",
                    {"first": 1, "after": cursor_or_null(comment_cursor)},
                    paged(
                        "reactions", {**FIRST_FEW, "after": cursor_or_null(after)}, obj
                    ),
                ),
            ),
        ),
    )
)

GQL_PR_THREADS_QUERY = pr_details_query("reviewThreads", GQL_REVIEW_THREAD)
GQL_PR_COMMITS_QUERY = pr_details_query("commits", GQL_COMMIT)
GQL_PR_REVIEWS_QUERY = pr_details_query("reviews", GQL_REVIEW)

GQL_GET_REPO_ID = lambda owner, repository: query(
    "query get_repo_id",
    func("repository", {"owner": f'"{owner}"', "name": f'"{repository}"'}, "id"),
)

# endregion query

# region mutations


def input(**args) -> dict[str, str]:
    extra = ", ".join(f"{k}: {v}" for k, v in args.items())
    return {"input": f"{{ {extra} }}"}


GQL_ADD_COMMENT = lambda comment_input: query(
    "mutation add_pr_comment",
    func(
        "addComment", comment_input, "clientMutationId"
    ),
)
GQL_UPDATE_COMMENT = lambda comment_input: query(
    "mutation update_pr_comment",
    func("updateIssueComment", comment_input, "clientMutationId"),
)


GQL_CREATE_PR = lambda pr_input: query(
    "mutation create_pr",
    func(
        "createPullRequest",
        pr_input,
        "clientMutationId",
        obj("pullRequest", GQL_PR),
    ),
)

GQL_UPDATE_PR_BASE = lambda pr_input: query(
    "mutation update_pr",
    func(
        "updatePullRequest",
        pr_input,
        "clientMutationId",
    ),
)
# endregion mutations

# region classes


class Pages(Generic[T]):
    def __init__(self, node: any, name: str, data: list[T] | None = None) -> None:
        super().__init__()
        self.name = name
        self.next_cursor: str = cursor(node, name)
        self.end_cursor: str = end_cursor(node, name)
        self.data = list(data) if data else []
        self._never_queried = data is None

    def complete(self) -> bool:
        return self.next_cursor == self.end_cursor and not self._never_queried

    def append_all(self, token: str, maker: Callable[[any], T], next_page):
        logging.debug(
            f"querying all {self.name} {self._never_queried=}, {self.next_cursor=}, {self.end_cursor=}"
        )
        while not self.complete():
            logging.debug(f"querying {self.name} after cursor {self.next_cursor}")
            response = graphql(token, next_page(self.next_cursor))
            if "data" not in response:
                raise Exception("GitHub GraphQL: No data in response")
            data = response["data"]
            self._never_queried = False
            if not self.end_cursor:
                self.end_cursor = end_cursor(data, self.name)
                logging.debug(f"end cursor {self.end_cursor}")
            self.data.extend(map(maker, edges(data, self.name)))
            self.next_cursor = cursor(data, self.name)
        logging.debug(f"queried all {self.name}")


@dataclass
class Author:
    login: str
    name: str | None

    def __str__(self) -> str:
        if self.name and self.login:
            return f"{self.name} ({self.login})"
        return self.name or self.login


@dataclass
class Reaction:
    content: str
    author: Author


@dataclass
class Comment:
    id: str
    author: Author
    body: str
    reacted: bool
    url: str
    reactions: Pages[Reaction]
    cursor: str


@dataclass
class CodeThread:
    path: str
    resolved: bool
    outdated: bool
    comments: Pages[Comment]


@dataclass
class Review:
    author: Author
    state: str
    url: str


@dataclass
class Commit:
    comments: Pages[Comment]


@dataclass
class PR:
    number: int
    id: str
    author: Author
    title: str
    state: str
    closed: bool
    merged: bool
    locked: bool
    draft: bool
    base: str
    head: str
    threads: Pages[CodeThread]
    comments: Pages[Comment]
    reviews: Pages[Review]
    commits: Pages[Commit]

    def __hash__(self) -> int:
        return self.number


# endregion classes


# region helpers
def _path(obj: any, *keys: str) -> any:
    for k in keys:
        if k in obj:
            obj = obj[k]
        else:
            return None
    return obj


def edges(obj: any, name: str) -> Iterator[any]:
    edges = _path(obj, name, "edges")
    if edges:
        for edge in edges:
            yield edge


def cursor(obj: any, field: str) -> str:
    if not obj:
        return None
    edges = _path(obj, field, "edges")
    return edges[-1]["cursor"] if edges else None


def end_cursor(obj: any, field: str) -> str:
    if not obj:
        return None
    return _path(obj, field, "pageInfo", "endCursor")


# endregion helpers

# region constructors


def _make_author(obj: any) -> Author:
    return Author(
        login=obj["login"],
        name=_path(obj, "name"),
    )


def _make_reaction(edge: any) -> Reaction:
    node = edge["node"]
    return Reaction(
        content=node["content"],
        author=_make_author(node["user"]),
    )


def query_reactions(subject: str, args: dict[str, any]):
    query("query reactions", func(subject, args, GQL_REACTION))


def query_pr_comments(owner: str, repository: str, pr: int):
    query(
        "query pr_comments",
        func(
            "repository",
            {"owner": f'"{owner}"', "name": f'"{repository}"'},
            func("pullRequest", {"id": pr}),
            GQL_COMMENT,
        ),
    )


def _make_comment(edge: any) -> Comment:
    node = edge["node"]
    logging.debug(f"found comment {node['id']}")
    return Comment(
        id=node["id"],
        author=_make_author(node["author"]),
        body=node["body"],
        reacted=False,
        url=node["url"],
        reactions=Pages(
            node,
            "reactions",
            map(_make_reaction, edges(node, "reactions")),
        ),
        cursor=edge["cursor"],
    )


def _make_review(edge: any) -> Review:
    node = edge["node"]
    return Review(
        author=_make_author(node["author"]), state=node["state"], url=node["url"]
    )


def _make_commit(edge: any) -> Commit:
    node = edge["node"]
    return Commit(
        comments=Pages(
            node,
            "comments",
            map(_make_comment, edges(node, "comments")),
        ),
    )


def _make_thread(edge: any) -> CodeThread:
    node = edge["node"]
    logging.debug(f"found review thread {node}")
    return CodeThread(
        path=node["path"],
        resolved=node["isResolved"],
        outdated=node["isOutdated"],
        comments=Pages(
            node,
            "comments",
            map(_make_comment, edges(node, "comments")),
        ),
    )


def make_pr(edge: any) -> PR:
    node = edge["node"]
    return PR(
        number=node["number"],
        id=node["id"],
        author=_make_author(node["author"]),
        title=node["title"],
        draft=node["isDraft"],
        locked=node["locked"],
        closed=node["closed"],
        merged=node["merged"],
        state=node["state"],
        base=node["baseRefName"],
        head=node["headRefName"],
        comments=Pages(
            node,
            "comments",
            map(_make_comment, edges(node, "comments")),
        ),
        threads=Pages(
            node,
            "reviewThreads",
            map(_make_thread, edges(node, "reviewThreads")),
        ),
        reviews=Pages(node, "reviews", map(_make_review, edges(node, "reviews"))),
        commits=Pages(node, "commits", map(_make_commit, edges(node, "commits"))),
    )


# endregion constructors


def graphql(token: str, query: str) -> any:
    logging.debug(f"query: {query}")
    response = requests.post(
        url=f"https://api.github.com/graphql",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        json={"query": query},
    )
    logging.debug(f"response: {response.status_code}")
    if not response.ok:
        raise BaseException(response.text)
    result = response.json()
    logging.debug(f"response json: {result}")
    if "errors" in result:
        for error in result["errors"]:
            if "type" in error:
                print(f"{error['type']}: {error['message']}", file=sys.stderr)
            else:
                print(error["message"], file=sys.stderr)

        raise BaseException("errors in GraphQL response")
    return result


###


def search_prs(
    token: str, owner: str, repository: str, branches: list[str] = []
) -> list[PR]:
    if not branches:
        return []

    heads = " ".join(f"head:{branch}" for branch in branches)
    next_page = lambda after: GQL_PRS_QUERY(owner, repository, heads, after)

    prsPages = Pages(None, "search")
    prsPages.append_all(token, make_pr, next_page)
    prs = prsPages.data

    for pr in prs:
        if not pr.comments.complete():
            next_page = lambda after: GQL_PR_COMMENTS_QUERY(
                owner, repository, pr.number, after
            )
            pr.comments.append_all(token, _make_comment, next_page)
            for comment in pr.comments.data:
                if not comment.reactions.complete():
                    next_page = lambda after: GQL_PR_COMMENT_REACTIONS_QUERY(
                        owner, repository, pr.number, comment.cursor, after
                    )
                    comment.reactions.append_all(token, _make_reaction, next_page)

        if not pr.threads.complete():
            next_page = lambda after: GQL_PR_THREADS_QUERY(
                owner, repository, pr.number, after
            )
            pr.threads.append_all(token, _make_comment, next_page)
        if not pr.reviews.complete():
            next_page = lambda after: GQL_PR_REVIEWS_QUERY(
                owner, repository, pr.number, after
            )
            pr.reviews.append_all(token, _make_review, next_page)
            pass
        if not pr.commits.complete():
            next_page = lambda after: GQL_PR_COMMITS_QUERY(
                owner, repository, pr.number, after
            )
            pr.commits.append_all(token, _make_commit, next_page)
            pass
    return prs
