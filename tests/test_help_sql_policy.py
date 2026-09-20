"""Helpの上流コードを変更しない生成物ポリシーを検証する。"""
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def policy(tmp_path):
    source = Path(__file__).resolve().parents[1] / 'build-console/server.py'
    spec = importlib.util.spec_from_file_location('help_policy_server', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    subprocess.run(['git', 'init', str(tmp_path)], check=True, capture_output=True)
    (tmp_path / 'docs').mkdir()
    (tmp_path / 'build').mkdir()
    def run(mode):
        return subprocess.run([sys.executable, '-c', module.HELP_SQL_POLICY, str(tmp_path), mode], capture_output=True)
    return module, run


def test_merge_preserves_sql_and_only_removes_generated_outputs(policy, tmp_path):
    _, run = policy
    first = "INSERT INTO ohr_help VALUES ('a', 'docs/a/', '日本語');"
    second = "INSERT INTO ohr_help VALUES ('b', 'docs/b/', 'O''Brien');"
    (tmp_path / 'docs/insert_ohr_help_a.sql').write_text(first, encoding='utf-8')
    (tmp_path / 'docs/insert_ohr_help_b.sql').write_text(second, encoding='utf-8-sig')
    (tmp_path / 'build/insert_ohr_help_a.sql').write_text(first, encoding='utf-8')
    (tmp_path / 'docs/manual.md').write_text('manual')
    assert run('normalize').returncode == 0
    assert (tmp_path / 'docs/insert_ohr_help.sql').read_text(encoding='utf-8') == first + '\n' + second
    assert not list((tmp_path / 'docs').glob('insert_ohr_help_*.sql'))
    assert not list((tmp_path / 'build').glob('*.sql'))
    assert (tmp_path / 'docs/manual.md').read_text() == 'manual'
    assert run('normalize').returncode == 0


def test_prepare_cleans_stale_outputs_and_single_is_preserved(policy, tmp_path):
    _, run = policy
    path = tmp_path / 'docs/insert_ohr_help.sql'
    path.write_bytes(b'original\r\n')
    assert run('normalize').returncode == 0
    assert path.read_bytes() == b'original\r\n'
    assert run('prepare').returncode == 0
    assert not path.exists()
    assert run('normalize').returncode != 0


def test_conflicting_outputs_and_tracked_files_fail_without_change(policy, tmp_path):
    _, run = policy
    single = tmp_path / 'docs/insert_ohr_help.sql'
    split = tmp_path / 'docs/insert_ohr_help_default.sql'
    single.write_text('one')
    split.write_text('two')
    assert run('normalize').returncode != 0
    assert single.read_text() == 'one' and split.read_text() == 'two'
    subprocess.run(['git','-C',str(tmp_path),'add','docs/insert_ohr_help.sql'], check=True)
    assert run('prepare').returncode != 0
    assert single.read_text() == 'one' and split.read_text() == 'two'


def test_integration_uses_policy_hash_and_never_commits_or_pushes(policy):
    module, _ = policy
    script = module.DIRECT_FRONTEND_BUILD_SCRIPT
    assert '__HELP_SQL_POLICY' not in script
    assert '"$HELP_LOCK_HASH" "$HELP_SQL_POLICY_HASH"' in script
    assert 'remote.origin.pushurl' in script
    help_step = script[script.index('HELP_DIR="$HELP_DOCS_WORKDIR"'):script.index('Help 构建已跳过')]
    assert help_step.index('normalize_help_sql prepare') < help_step.index('npm run build')
    assert help_step.index('npm run build') < help_step.index('normalize_help_sql normalize') < help_step.index('npm run bundle')
    assert 'git push' not in help_step and 'git commit' not in help_step
    assert help_step.index('fetch --no-tags') < help_step.index('if [ -f "$HELP_CACHED_ZIP" ]')
    assert help_step.index('svn update') < help_step.index('if [ -f "$HELP_CACHED_ZIP" ]')


def test_full_upstream_sync_preserves_policy_and_fails_closed(policy, tmp_path):
    module, _ = policy
    upstream = tmp_path / 'upstream'
    checkout = tmp_path / 'checkout'
    def git(*args):
        return subprocess.run(['git', '-C', str(upstream), *args], check=True, capture_output=True)
    upstream.mkdir()
    git('init', '-b', 'release_ci')
    git('config', 'user.name', 'fixture')
    git('config', 'user.email', 'fixture@example.invalid')
    (upstream / 'changed.txt').write_text('v1')
    (upstream / 'deleted.txt').write_text('old')
    git('add', '.')
    git('commit', '-m', 'fixture one')
    env = dict(os.environ, HELP_DIR=checkout.as_posix(), HELP_DOCS_GIT_URL=upstream.as_posix(), HELP_DOCS_BRANCH='release_ci')
    def sync():
        return subprocess.run([os.environ.get('BASH_EXE', 'bash'), '-c', module.HELP_SOURCE_SYNC], env=env, capture_output=True)
    first = sync()
    assert first.returncode == 0, first.stderr
    (checkout / '.ci-cache').mkdir()
    (checkout / '.ci-cache/old.zip').write_bytes(b'cached')
    (upstream / 'changed.txt').write_text('v2')
    (upstream / 'deleted.txt').unlink()
    (upstream / 'added.txt').write_text('new')
    git('add', '-A')
    git('commit', '-m', 'fixture two')
    second = sync()
    assert second.returncode == 0, second.stderr
    assert (checkout / 'changed.txt').read_text() == 'v2'
    assert (checkout / 'added.txt').read_text() == 'new'
    assert not (checkout / 'deleted.txt').exists()
    assert b'changed.txt' in second.stdout and b'deleted.txt' in second.stdout
    assert (checkout / '.ci-cache/old.zip').read_bytes() == b'cached'
    assert sync().returncode == 0
    # 遠隔更新後も同じローカル生成物ポリシーを適用できる。
    (checkout / 'docs').mkdir()
    (checkout / 'docs/insert_ohr_help_a.sql').write_text('SELECT 1;')
    normalized = subprocess.run([sys.executable, '-c', module.HELP_SQL_POLICY, str(checkout), 'normalize'], capture_output=True)
    assert normalized.returncode == 0, normalized.stderr
    (checkout / 'docs/insert_ohr_help.sql').unlink()
    (checkout / 'changed.txt').write_text('local edit')
    assert sync().returncode != 0
    assert (checkout / 'changed.txt').read_text() == 'local edit'
    (checkout / 'changed.txt').write_text('v2')
    (checkout / 'local.txt').write_text('local addition')
    assert sync().returncode != 0
    assert (checkout / 'local.txt').read_text() == 'local addition'
    (checkout / 'local.txt').unlink()
    env['HELP_DOCS_GIT_URL'] = (tmp_path / 'missing-remote').as_posix()
    assert sync().returncode != 0
    assert (checkout / 'changed.txt').read_text() == 'v2'
