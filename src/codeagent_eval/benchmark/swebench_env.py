"""Building runnable environments for real SWE-bench instances, without Docker.

The official harness ships a container per instance because reproducing a repository's
dependency set at a historical commit is the hard part of SWE-bench — harder, usually, than
the patch itself. This module does the same job locally for the subset of repositories where
it is tractable: pure-Python projects whose dependencies still install on a current
interpreter. That subset is declared explicitly rather than discovered, so an instance from an
unsupported repository fails loudly instead of producing a zero that looks like an agent
failure.

Three things here exist because getting them wrong produces results that look plausible:

**The interpreter must import the trial's worktree, not the shared clone.** The natural setup —
one editable install of the cached repository, one worktree per trial — silently ignores every
patch: the tests import the shared copy, so the gold patch and the agent's patch alike have no
effect and every instance reports unresolved. Measured, that is exactly what happened. The
worktree's source directory is therefore prepended to ``PYTHONPATH`` for every run.

**Test node ids must be passed as argv and never through a shell or a line-delimited file.**
Real ids contain brackets, quotes and — in several requests and flask instances — embedded
newlines, because pytest parametrize ids inherit the repr of their arguments. Splitting on
newlines truncates them, pytest exits with "not found", and the whole batch reports zero tests
run. Dropping PASS_TO_PASS ids that way makes *resolved* easier to reach, so the failure
inflates the score rather than depressing it.

**Whatever ends up installed is recorded.** Runtime dependencies in these projects are
lower-bounded and not pinned, so a 2023 Flask installs against today's Werkzeug. That may or
may not matter for a given instance, and the honest answer is to freeze the environment into
the result and let the gold run say whether it was good enough.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import venv
from dataclasses import dataclass, field
from pathlib import Path

#: Where clones, worktrees and per-environment interpreters live. Kept out of the repository.
DEFAULT_CACHE = Path(".swebench_cache")


class UnsupportedInstance(RuntimeError):
    """Raised for a repository this module cannot build locally.

    Loud on purpose: an instance that cannot be built is missing evidence, and scoring it as
    unresolved would blend an environment gap into the agent's failure rate.
    """


@dataclass(frozen=True)
class RepoSpec:
    """How to build one repository's environment, and where its importable source lives."""

    repo: str
    #: Path inside the worktree that must precede site-packages on ``PYTHONPATH``. Projects
    #: using a ``src/`` layout need it; older flat-layout projects import from the root.
    source_dir: str = ""
    #: Requirement files inside the repository, tried in order; the first present one is used.
    requirement_files: tuple[str, ...] = ()
    #: Extra requirements installed after the repository itself.
    extra_requirements: tuple[str, ...] = ()
    #: Distribution name to uninstall once its dependencies are in place, so nothing shadows
    #: the trial's own source. Required for every supported repository.
    distribution: str = ""
    #: Per-version dependency pins. These projects lower-bound their runtime dependencies and
    #: never upper-bound them, so pip resolves to today's release: Flask 2.3 installs against
    #: Werkzeug 3, which removed ``werkzeug.urls.url_quote`` and makes the package unimportable.
    #: Gold validation is what surfaces that, and a pin is what fixes it.
    pins: dict[str, tuple[str, ...]] = field(default_factory=dict)

    @property
    def clone_url(self) -> str:
        return f"https://github.com/{self.repo}.git"

    @property
    def slug(self) -> str:
        return self.repo.replace("/", "__")


#: Repositories this module can build. Deliberately small and explicit — every entry here has
#: been validated by running its instances' gold patches, which is the only evidence that an
#: environment is right.
SUPPORTED_REPOS: dict[str, RepoSpec] = {
    "pallets/flask": RepoSpec(
        repo="pallets/flask",
        source_dir="src",
        requirement_files=("requirements/tests.txt",),
        extra_requirements=("pytest",),
        distribution="Flask",
        pins={
            # pytest is pinned too: Flask 2.0's conftest reaches into `_pytest.monkeypatch`
            # for a private attribute that pytest 7 removed, so a modern pytest cannot even
            # collect the suite.
            "2.0": ("Werkzeug<2.1", "Jinja2<3.1", "itsdangerous<2.1", "click<8.1", "pytest<7"),
            "2.3": ("Werkzeug<3", "Jinja2<3.2", "itsdangerous<2.2", "click<8.2"),
        },
    ),
}

#: Repositories deliberately not supported, with the reason. Kept next to the supported table
#: so "unsupported" is a recorded judgement rather than an omission.
KNOWN_UNSUPPORTED: dict[str, str] = {
    "psf/requests": (
        "the 2012-2016 releases in SWE-bench Lite vendor urllib3, chardet and idna inside "
        "requests/packages and declare no dependencies, so the package cannot import without "
        "an era-matched set installed alongside it; the test suite then needs pytest-httpbin, "
        "which pulls httpbin and an old Flask. Reproducing that chain is what the official "
        "Docker images exist for."
    ),
}


@dataclass
class BuiltEnvironment:
    """A ready interpreter plus the provenance needed to interpret a result from it."""

    python: Path
    repo_spec: RepoSpec
    version: str
    frozen: tuple[str, ...] = field(default_factory=tuple)
    install_errors: tuple[str, ...] = field(default_factory=tuple)

    def manifest(self) -> dict[str, object]:
        return {
            "repo": self.repo_spec.repo,
            "version": self.version,
            "python": str(self.python),
            "source_dir": self.repo_spec.source_dir,
            "frozen_packages": list(self.frozen),
            "install_errors": list(self.install_errors),
        }


def _run(argv: list[str], cwd: Path | None = None, timeout: int = 900) -> subprocess.CompletedProcess:
    return subprocess.run(
        argv, cwd=str(cwd) if cwd else None, capture_output=True, text=True,
        timeout=timeout, check=False,
    )


def spec_for(repo: str) -> RepoSpec:
    spec = SUPPORTED_REPOS.get(repo)
    if spec is None:
        known = KNOWN_UNSUPPORTED.get(repo)
        if known:
            raise UnsupportedInstance(f"{repo} is not buildable locally: {known}")
        raise UnsupportedInstance(
            f"{repo} has no local environment recipe; supported: "
            f"{', '.join(sorted(SUPPORTED_REPOS))}. Building it needs its historical "
            f"dependency set, which is why the official harness uses Docker."
        )
    return spec


def ensure_clone(spec: RepoSpec, cache: Path = DEFAULT_CACHE) -> Path:
    """Clone once per repository, blobless, and reuse it for every instance."""
    clone = Path(cache) / "repos" / spec.slug
    if (clone / ".git").is_dir():
        return clone
    clone.parent.mkdir(parents=True, exist_ok=True)
    done = _run(["git", "clone", "--filter=blob:none", "--quiet", spec.clone_url, str(clone)])
    if done.returncode != 0:
        raise UnsupportedInstance(f"clone failed for {spec.repo}: {done.stderr.strip()[:300]}")
    return clone


def checkout_worktree(spec: RepoSpec, commit: str, destination: Path,
                      cache: Path = DEFAULT_CACHE) -> Path:
    """Create a detached worktree at ``commit``. Each trial gets its own."""
    clone = ensure_clone(spec, cache)
    destination = destination.resolve()
    # Idempotent by construction: a previous run may have left the directory, git's worktree
    # metadata, or both. Either alone makes `worktree add` fail, and a half-cleaned cache is
    # the normal state after an interrupted run.
    _run(["git", "worktree", "remove", "--force", str(destination)], clone)
    shutil.rmtree(destination, ignore_errors=True)
    _run(["git", "worktree", "prune"], clone)
    destination.parent.mkdir(parents=True, exist_ok=True)
    done = _run(["git", "worktree", "add", "-q", "--detach", str(destination), commit], clone)
    if done.returncode != 0:
        raise UnsupportedInstance(
            f"worktree at {commit[:10]} failed for {spec.repo}: {done.stderr.strip()[:300]}"
        )
    return destination


def build_environment(spec: RepoSpec, version: str, setup_commit: str,
                      cache: Path = DEFAULT_CACHE) -> BuiltEnvironment:
    """Create (or reuse) one interpreter per repository *version*.

    Instances of the same version share dependencies, so the expensive step happens once. The
    trial's own source is layered on at run time through ``PYTHONPATH`` rather than installed,
    which keeps concurrent trials from sharing a mutable install.
    """
    cache = Path(cache)
    env_dir = Path(cache).resolve() / "venvs" / f"{spec.slug}-{version}"
    python = env_dir / "bin" / "python"
    marker = env_dir / ".algora-ready.json"
    if marker.is_file() and python.is_file():
        recorded = json.loads(marker.read_text())
        return BuiltEnvironment(
            python=python, repo_spec=spec, version=version,
            frozen=tuple(recorded.get("frozen_packages", ())),
            install_errors=tuple(recorded.get("install_errors", ())),
        )

    cache = cache.resolve()
    setup_tree = cache / "setup" / f"{spec.slug}-{version}"
    checkout_worktree(spec, setup_commit, setup_tree, cache)

    shutil.rmtree(env_dir, ignore_errors=True)
    venv.create(env_dir, with_pip=True)
    errors: list[str] = []

    def pip(*args: str) -> None:
        # Paths must be absolute: pip reads a bare relative path as a requirement *name*, so
        # `pip install -e .swebench_cache/...` fails with a VCS-URL error and the repository
        # silently never gets installed.
        done = _run([str(python), "-m", "pip", "install", "-q", "--disable-pip-version-check", *args])
        if done.returncode != 0:
            errors.append(f"pip install {' '.join(args)[:80]}: {done.stderr.strip()[-300:]}")

    pip("--upgrade", "pip", "setuptools", "wheel")
    # The repository itself brings its declared runtime dependencies. It is installed from the
    # setup tree; per-trial source is layered over it later, never installed.
    pip("-e", str(setup_tree))
    for candidate in spec.requirement_files:
        if (setup_tree / candidate).is_file():
            pip("-r", str(setup_tree / candidate))
            break
    if spec.extra_requirements:
        pip(*spec.extra_requirements)
    pinned = spec.pins.get(version, ())
    if pinned:
        # Applied last so they win over whatever the project's own metadata resolved to.
        pip(*pinned)

    # The project is installed only to resolve its dependencies, then removed. An editable
    # install registers a .pth that wins over PYTHONPATH, so leaving it in place makes every
    # trial import the shared setup tree instead of its own worktree — measured, that made the
    # gold patch invisible and every instance report unresolved. Uninstalling keeps the venv
    # read-only during trials, which also lets them run concurrently.
    if spec.distribution:
        _run([str(python), "-m", "pip", "uninstall", "-y", "-q", spec.distribution])

    frozen = _run([str(python), "-m", "pip", "freeze"])
    packages = tuple(sorted(line.strip() for line in frozen.stdout.splitlines() if line.strip()))

    built = BuiltEnvironment(
        python=python, repo_spec=spec, version=version,
        frozen=packages, install_errors=tuple(errors),
    )
    marker.write_text(json.dumps(built.manifest(), indent=2))
    return built


def collect_node_ids(env: BuiltEnvironment, worktree: Path, files: set[str],
                     timeout: int = 900) -> list[str]:
    """Ask pytest what ids actually exist in these files."""
    if not files:
        return []
    worktree = Path(worktree).resolve()
    source_root = worktree / env.repo_spec.source_dir if env.repo_spec.source_dir else worktree
    done = subprocess.run(
        [str(env.python), "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider",
         *sorted(files)],
        cwd=str(worktree),
        env={"PATH": "/usr/bin:/bin", "HOME": str(Path.home()), "PYTHONPATH": str(source_root),
             "PYTHONDONTWRITEBYTECODE": "1", "LANG": "en_US.UTF-8"},
        capture_output=True, text=True, timeout=timeout, check=False,
    )
    return [line.strip() for line in done.stdout.splitlines() if "::" in line]


@dataclass(frozen=True)
class ResolvedIds:
    """Dataset ids matched against what pytest can actually collect."""

    matched: tuple[str, ...] = ()
    #: Dataset ids repaired by unique prefix match. SWE-bench derived these lists from wrapped
    #: pytest output, so ids containing spaces are truncated at the wrap — for example
    #: ``test_locate_app[cliapp.factory-create_app2("foo",`` with the rest of the parameter
    #: missing. The repair is recorded, never silent.
    repaired: tuple[tuple[str, str], ...] = ()
    #: Ids that match nothing, or match several collected ids ambiguously.
    unmatched: tuple[str, ...] = ()


def resolve_node_ids(dataset_ids: list[str], collected: list[str]) -> ResolvedIds:
    """Map dataset ids onto collectable ones, repairing truncation where it is unambiguous.

    Dropping an id that will not match is not a neutral act: PASS_TO_PASS is a conjunction, so
    every dropped id makes *resolved* easier to reach. Unmatched ids are therefore reported so
    an instance is never quietly scored against a shortened oracle.
    """
    available = set(collected)
    matched: list[str] = []
    repaired: list[tuple[str, str]] = []
    unmatched: list[str] = []
    for wanted in dataset_ids:
        if wanted in available:
            matched.append(wanted)
            continue
        candidates = [c for c in collected if c.startswith(wanted)]
        if len(candidates) == 1:
            matched.append(candidates[0])
            repaired.append((wanted, candidates[0]))
        else:
            unmatched.append(wanted)
    return ResolvedIds(tuple(matched), tuple(repaired), tuple(unmatched))


def run_node_ids(env: BuiltEnvironment, worktree: Path, node_ids: list[str],
                 timeout: int = 900) -> tuple[bool, str, int]:
    """Run exactly these pytest node ids in ``worktree``.

    Ids go through argv untouched. Several real ids contain embedded newlines and quotes, so
    any line-delimited or shell round trip silently drops tests — and a dropped PASS_TO_PASS
    id makes an instance easier to resolve, not harder.
    """
    if not node_ids:
        return True, "", 0
    # Absolute, because the child runs with cwd set to the worktree: a relative PYTHONPATH
    # would be resolved against that cwd and point at a directory inside the worktree that
    # does not exist, so the project silently fails to import and every test errors in
    # conftest — which reads as an unresolved instance rather than a harness bug.
    worktree = Path(worktree).resolve()
    source_root = worktree / env.repo_spec.source_dir if env.repo_spec.source_dir else worktree
    environment = {
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "HOME": str(Path.home()),
        "PYTHONPATH": str(source_root),
        "PYTHONDONTWRITEBYTECODE": "1",
        "LANG": "en_US.UTF-8",
    }
    done = subprocess.run(
        [str(env.python), "-m", "pytest", "-q", "-p", "no:cacheprovider", *node_ids],
        cwd=str(worktree), env=environment, capture_output=True, text=True,
        timeout=timeout, check=False,
    )
    output = (done.stdout or "") + (done.stderr or "")
    # Exit code 4 is pytest's usage error, which is what an unmatched id produces. Treating it
    # as "tests failed" would hide a harness bug as an agent result.
    if done.returncode == 4:
        return False, output[-4000:], done.returncode
    return done.returncode == 0, output[-4000:], done.returncode
