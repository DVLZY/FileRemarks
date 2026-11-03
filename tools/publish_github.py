#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Publish the FileRemarks sources to GitHub and attach the built installer.

Everything goes through the REST API over HTTPS, because in this environment
git over https cannot spawn its transport helper (the sandbox denies pipe
creation) and curl's schannel backend has no usable credentials. Python's own
TLS stack works, so this script is the transport.

What it does, in order:
  1. GET  /user                       -- who is the token for
  2. POST /user/repos                 -- create <login>/FileRemarks (or reuse it)
  3. build blobs + one tree + commit  -- exactly the files git tracks locally
  4. PATCH refs/heads/main            -- make that commit the branch head
  5. POST /releases                   -- tag v1.13 with the installer attached

The file list comes from `git ls-files`, so anything ignored (.gitignore:
build/, dist/, the toolchain, scratch probes) is never uploaded.

Usage:
    set GITHUB_TOKEN=ghp_xxx        (Windows cmd)
    export GITHUB_TOKEN=ghp_xxx     (bash)
    python tools/publish_github.py --repo-dir github_repo \
        --setup dist/releases/FileRemarks_Setup_v1.13.exe --tag v1.13

    python tools/publish_github.py ... --dry-run     # print the plan only
"""
import argparse
import base64
import json
import os
import re
import ssl
import subprocess
import sys
import urllib.error
import urllib.request

API = "https://api.github.com"
UPLOAD = "https://uploads.github.com"
UA = "FileRemarks-publisher/1.0"


class Failure(Exception):
    pass


class GitHub(object):
    def __init__(self, token, dry_run=False):
        self.token = token
        self.dry_run = dry_run
        self.ctx = ssl.create_default_context()

    def _open(self, req):
        try:
            with urllib.request.urlopen(req, timeout=120, context=self.ctx) as r:
                body = r.read()
                return r.status, body
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            raise Failure("%s %s -> HTTP %s: %s"
                          % (req.get_method(), req.full_url, exc.code,
                             body[:600]))

    def call(self, method, path, payload=None, host=API, raw=None,
             content_type="application/json"):
        url = host + path
        if raw is not None:
            data = raw
        elif payload is not None:
            data = json.dumps(payload).encode("utf-8")
        else:
            data = None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("User-Agent", UA)
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("Authorization", "Bearer " + self.token)
        req.add_header("X-GitHub-Api-Version", "2022-11-28")
        if data is not None:
            req.add_header("Content-Type", content_type)
        if self.dry_run and method != "GET":
            print("    [dry-run] %s %s" % (method, path))
            return None, b"{}"
        status, body = self._open(req)
        return status, body

    def json(self, method, path, payload=None, **kw):
        _, body = self.call(method, path, payload, **kw)
        text = body.decode("utf-8", "replace") if body else "{}"
        return json.loads(text) if text.strip() else {}


def git(repo_dir, *args):
    """Run git and capture its output WITHOUT pipes.

    This sandbox denies CreatePipe (PermissionError: [WinError 5]), so
    capture_output cannot be used; redirect stdout/stderr to temp files instead.
    """
    import tempfile
    out_fd, out_path = tempfile.mkstemp(suffix=".out")
    err_fd, err_path = tempfile.mkstemp(suffix=".err")
    os.close(out_fd)
    os.close(err_fd)
    try:
        with open(out_path, "wb") as out, open(err_path, "wb") as err:
            rc = subprocess.call(["git", "-C", repo_dir] + list(args),
                                 stdout=out, stderr=err)
        with open(out_path, "rb") as fh:
            stdout = fh.read().decode("utf-8", "replace")
        with open(err_path, "rb") as fh:
            stderr = fh.read().decode("utf-8", "replace")
    finally:
        for path in (out_path, err_path):
            try:
                os.remove(path)
            except OSError:
                pass
    if rc != 0:
        raise Failure("git %s failed: %s" % (" ".join(args), stderr))
    return stdout


def tracked_files(repo_dir, list_file=""):
    if list_file:
        with open(list_file, encoding="utf-8") as fh:
            names = fh.read().splitlines()
    else:
        names = git(repo_dir, "ls-files").splitlines()
    return [n for n in names if n.strip()]


def ensure_repo(gh, login, name, description, private):
    path = "/repos/%s/%s" % (login, name)
    try:
        repo = gh.json("GET", path)
        print("  repository already exists: %s" % repo["html_url"])
        return repo
    except Failure as exc:
        if "HTTP 404" not in str(exc):
            raise
    print("  creating repository %s/%s ..." % (login, name))
    repo = gh.json("POST", "/user/repos", {
        "name": name,
        "description": description,
        "private": private,
        "has_issues": True,
        "has_wiki": False,
        "has_projects": False,
    })
    print("  created: %s" % repo["html_url"])
    return repo


def ensure_initial_commit(gh, owner, name):
    """GitHub rejects blob creation with 409 "Git Repository is empty." until the
    repository has at least one commit, so seed one through the contents API.
    The real tree replaces it a moment later."""
    try:
        gh.json("GET", "/repos/%s/%s/git/ref/heads/main" % (owner, name))
        return
    except Failure as exc:
        # An empty repository answers 409 ("Git Repository is empty.") rather
        # than 404 for both the ref and the blob endpoints.
        if "HTTP 404" not in str(exc) and "HTTP 409" not in str(exc):
            raise
    print("  repository is empty -> seeding an initial commit")
    payload = base64.b64encode(b"# FileRemarks" + bytes([10])).decode("ascii")
    gh.json("PUT", "/repos/%s/%s/contents/README.md" % (owner, name),
            {"message": "initial commit", "content": payload})


def push_snapshot(gh, owner, name, repo_dir, message, list_file=""):
    files = tracked_files(repo_dir, list_file)
    print("  uploading %d files (from git ls-files) ..." % len(files))
    tree = []
    for rel in files:
        full = os.path.join(repo_dir, rel)
        with open(full, "rb") as fh:
            blob = base64.b64encode(fh.read()).decode("ascii")
        meta = gh.json("POST", "/repos/%s/%s/git/blobs" % (owner, name),
                       {"content": blob, "encoding": "base64"})
        tree.append({"path": rel.replace(os.sep, "/"),
                     "mode": "100644",
                     "type": "blob",
                     "sha": meta["sha"]})
        if len(tree) % 20 == 0:
            print("    %d/%d" % (len(tree), len(files)))

    new_tree = gh.json("POST", "/repos/%s/%s/git/trees" % (owner, name),
                       {"tree": tree})
    parents = []
    try:
        ref = gh.json("GET", "/repos/%s/%s/git/ref/heads/main" % (owner, name))
        parents = [ref["object"]["sha"]]
    except Failure as exc:
        if "HTTP 404" not in str(exc) and "HTTP 409" not in str(exc):
            raise
        print("  (branch main does not exist yet)")
    commit = gh.json("POST", "/repos/%s/%s/git/commits" % (owner, name),
                     {"message": message, "tree": new_tree["sha"],
                      "parents": parents})
    if parents:
        gh.json("PATCH", "/repos/%s/%s/git/refs/heads/main" % (owner, name),
                {"sha": commit["sha"], "force": False})
    else:
        gh.json("POST", "/repos/%s/%s/git/refs" % (owner, name),
                {"ref": "refs/heads/main", "sha": commit["sha"]})
    print("  commit %s is now the head of main" % commit["sha"][:12])
    return commit["sha"]


def ensure_release(gh, owner, name, tag, title, body, setup_path):
    try:
        rel = gh.json("GET", "/repos/%s/%s/releases/tags/%s" % (owner, name, tag))
        print("  release %s already exists: %s" % (tag, rel["html_url"]))
    except Failure as exc:
        if "HTTP 404" not in str(exc):
            raise
        print("  creating release %s ..." % tag)
        rel = gh.json("POST", "/repos/%s/%s/releases" % (owner, name), {
            "tag_name": tag,
            "name": title,
            "body": body,
            "draft": False,
            "prerelease": False,
        })
        print("  release created: %s" % rel["html_url"])

    if not setup_path:
        return rel
    asset_name = os.path.basename(setup_path)
    for asset in rel.get("assets", []):
        if asset["name"] == asset_name:
            print("  asset %s already attached (%d bytes)"
                  % (asset_name, asset["size"]))
            return rel
    size = os.path.getsize(setup_path)
    print("  uploading %s (%d bytes) ..." % (asset_name, size))
    with open(setup_path, "rb") as fh:
        data = fh.read()
    rel2 = gh.json("POST",
                   "/repos/%s/%s/releases/%d/assets?name=%s"
                   % (owner, name, rel["id"], urllib.request.quote(asset_name)),
                   host=UPLOAD, raw=data,
                   content_type="application/octet-stream")
    print("  asset uploaded: %s" % rel2.get("browser_download_url"))
    return rel


def default_version(repo_dir):
    """Tag/title default to the version in src/version.h, so a release can
    never be labeled with a stale hard-coded number again."""
    try:
        with open(os.path.join(repo_dir, "src", "version.h"),
                  encoding="utf-8") as fh:
            m = re.search(r'#define\s+FR_VERSION_TEXT\s+L"([^"]+)"', fh.read())
            if m:
                return m.group(1)
    except OSError:
        pass
    return "0.0"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-dir", default="github_repo",
                    help="local git checkout whose tracked files get published")
    args0, _ = ap.parse_known_args()
    ver = default_version(os.path.abspath(args0.repo_dir))

    ap.add_argument("--name", default="FileRemarks")
    ap.add_argument("--private", action="store_true")
    ap.add_argument("--tag", default="v" + ver)
    ap.add_argument("--setup",
                    default="dist/releases/FileRemarks_Setup_v%s.exe" % ver)
    ap.add_argument("--title", default="FileRemarks v" + ver)
    ap.add_argument("--description",
                    default="给任意文件加 Windows 资源管理器“备注”列的轻量工具"
                            "（属性处理器 + 右键菜单 + Shift+F2，免管理员安装）")
    ap.add_argument("--message", default="FileRemarks v%s sources" % ver)
    ap.add_argument("--body-file", default="")
    ap.add_argument("--file-list", default="",
                    help="optional file with one tracked path per line")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        print("GITHUB_TOKEN is not set.\n"
              "Create a token at https://github.com/settings/tokens with the "
              "'repo' scope (classic) or Contents+Administration write "
              "(fine-grained), then:\n"
              "  set GITHUB_TOKEN=...   (cmd)  /  export GITHUB_TOKEN=...  (bash)",
              file=sys.stderr)
        return 2

    repo_dir = os.path.abspath(args.repo_dir)
    if not os.path.isdir(os.path.join(repo_dir, ".git")):
        print("%s is not a git checkout" % repo_dir, file=sys.stderr)
        return 2

    body = "本次发布包含 v%s 的全部源码与安装包。" % ver
    if args.body_file and os.path.exists(args.body_file):
        with open(args.body_file, encoding="utf-8") as fh:
            body = fh.read()

    gh = GitHub(token, dry_run=args.dry_run)
    print("1/5  who am I")
    me = gh.json("GET", "/user")
    login = me["login"]
    print("  logged in as %s" % login)

    print("2/5  repository")
    repo = ensure_repo(gh, login, args.name, args.description, args.private)

    print("3/5  files")
    ensure_initial_commit(gh, login, args.name)
    sha = push_snapshot(gh, login, args.name, repo_dir, args.message, args.file_list)

    print("4/5  release")
    setup = os.path.abspath(args.setup) if args.setup else ""
    ensure_release(gh, login, args.name, args.tag, args.title, body,
                   setup if os.path.exists(setup) else None)

    print("5/5  done")
    print("  repository : %s" % repo["html_url"])
    print("  commit     : %s" % sha)
    print("  release    : %s/releases/tag/%s" % (repo["html_url"], args.tag))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Failure as exc:
        print("\nFAILED: %s" % exc, file=sys.stderr)
        raise SystemExit(1)
