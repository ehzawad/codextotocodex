from __future__ import annotations


def test_context_includes_all_titles_by_default(chronicle_env):
    from codex_chronicle import context
    from codex_chronicle.config import project_chronicle_dir, project_slug_from_path

    project = "/tmp/demo"
    slug = project_slug_from_path(project)
    sessions = project_chronicle_dir(slug) / "sessions"
    sessions.mkdir(parents=True)
    for idx in range(12):
        (sessions / f"2026-04-{idx:02d}.md").write_text(f"# Session {idx}\n")

    out = context.build_context(project)
    assert "Session 0" in out
    assert "Session 11" in out


def test_context_includes_full_chronicle_by_default(chronicle_env):
    from codex_chronicle import context
    from codex_chronicle.config import project_chronicle_dir, project_slug_from_path

    project = "/tmp/demo"
    slug = project_slug_from_path(project)
    project_dir = project_chronicle_dir(slug)
    project_dir.mkdir(parents=True)
    body = "x" * 20000
    (project_dir / "chronicle.md").write_text(body)

    out = context.build_context(project, include_chronicle=True)
    assert "[truncated]" not in out
    assert body in out


def test_context_max_bytes_is_explicit_cap(chronicle_env):
    from codex_chronicle import context
    from codex_chronicle.config import project_chronicle_dir, project_slug_from_path

    project = "/tmp/demo"
    slug = project_slug_from_path(project)
    project_dir = project_chronicle_dir(slug)
    project_dir.mkdir(parents=True)
    (project_dir / "chronicle.md").write_text("x" * 20000)

    out = context.build_context(project, include_chronicle=True, max_bytes=1000)
    assert "[truncated]" in out
