"""Disposable current-contract Git snapshots for offline integration tests."""
from pathlib import Path
import subprocess
import tempfile

from pr_review.context import ContextReader
from pr_review.service import prepare


class FakeGithub:
    def __init__(self, data):
        self.data = data
        self.items = []
        self.posts = 0
        self.uncertain = False

    def pr(self):
        return {"state": "open", "draft": False, "user": {"type": "User"},
                "title": self.data.get("metadata", {}).get("title", "Adjust summary contract"),
                "body": self.data.get("metadata", {}).get("body", "Review the producer and its caller."),
                "base": {"ref": "main", "sha": self.data["base"]},
                "head": {"sha": self.data["head"], "repo": {"full_name": self.data["repository"]}}}

    def reviews(self):
        return self.items

    def post(self, body):
        from pr_review.core import ReviewError
        self.posts += 1
        self.items.append({"user": {"login": "github-actions[bot]", "type": "Bot"},
                           "state": "COMMENTED", "commit_id": body["commit_id"], "body": body["body"]})
        if self.uncertain:
            raise ReviewError("timeout")
        return {"id": self.posts}


class ReviewFixture:
    def __init__(self):
        self.directory = tempfile.TemporaryDirectory()
        self.repository = Path(self.directory.name)
        self.git("init", "--quiet", "-b", "main")
        self.git("config", "user.name", "Offline Fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        self.write("contract.py", 'def summary(value):\n    return {"total": value}\n')
        self.write("caller.py", 'from contract import summary\nprint(summary(1)["total"])\n')
        self.commit("Before contract adjustment")
        self.base = self.git("rev-parse", "HEAD")
        self.write("contract.py", 'def summary(value):\n    return {"amount": value}\n')
        self.commit("Adjust returned summary key")
        self.refresh()

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.repository), *args], text=True, stderr=subprocess.DEVNULL).strip()

    def write(self, path, content):
        target = self.repository / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def commit(self, message):
        self.git("add", "--all")
        self.git("-c", "core.hooksPath=/dev/null", "commit", "--quiet", "-m", message)

    def refresh(self):
        identity = {"repository": "offline/fixture", "pr": 1, "base": self.base,
                    "head": self.git("rev-parse", "HEAD")}
        self.data = prepare(FakeGithub(identity), identity["repository"], 1, self.repository)
        reader = ContextReader(self.repository, self.data)
        source = next(s for s in reader.initial_context() if s["path"] == "contract.py")
        reference = {key: value for key, value in source.items() if key != "text"}
        self.content = {"status": "complete", "summary": "The renamed key breaks the unchanged caller.",
                        "limitations": [], "findings": [{"severity": "high", "description": "The caller requires the total key.",
                        "evidence": "The returned dictionary now contains amount instead of total.",
                        "recommendation": "Preserve the total response key.",
                        "anchor": {"file": "contract.py", "side": "RIGHT", "start": 2, "end": 2},
                        "references": [reference]}]}
        return self.data

    def clean(self):
        return {"status": "complete", "summary": "No supported defects found.", "findings": [], "limitations": []}

    def close(self):
        self.directory.cleanup()
