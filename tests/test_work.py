import asyncio
from pathlib import Path

from tools.data_tools import WorkPython, Toolbox, definitions


def test_work_is_declared_and_input_is_bounded():
    assert 'work_python' in {item['name'] for item in definitions()}
    assert WorkPython(code='print(1)').stdin == ''


def test_work_runtime_isolation():
    from wasi_python import run
    code = '''import os\nprint("ENV", "OPENAI_API_KEY" in os.environ)\ntry:\n print(open("C:/Apps/atlas_agent/.config/.env").read())\nexcept OSError:\n print("FILE DENIED")\ntry:\n import socket\n socket.socket()\n print("SOCKET AVAILABLE")\nexcept Exception:\n print("NETWORK DENIED")\n'''
    result = run(['-c', code], root=False, grants=(), mounts=(), env={}, deadline_s=15, memory_bytes=536870912, output_bytes=16000, fuel=10000000000)
    output = result.stdout.decode()
    assert result.exit_code == 0
    assert 'ENV False' in output and 'FILE DENIED' in output and 'NETWORK DENIED' in output


def test_work_executes_code():
    result = asyncio.run(Toolbox.work_python(None, WorkPython(code='print(6 * 7)')))
    assert result['exit_code'] == 0
    assert result['stdout'].strip() == '42'

def test_work_stops_infinite_loop():
    from wasi_python import run
    result = run(['-c', 'while True: pass'], root=False, deadline_s=0.5, memory_bytes=536870912, output_bytes=16000, fuel=10000000000)
    assert result.trapped is not None


def test_work_creates_downloadable_file(tmp_path):
    from types import SimpleNamespace
    class Store:
        def save_artifact(self, run_id, title, extension, content):
            assert run_id == 'run' and title == 'dados.csv' and extension == 'csv'
            assert content == b'a,b\n1,2\n'
            (tmp_path / 'file.csv').write_bytes(content)
            return {'url': '/api/artifacts/test', 'title': title, 'filename': 'file.csv'}
        artifacts_dir = tmp_path
    context = SimpleNamespace(run=SimpleNamespace(id='run', artifacts=[]), store=Store())
    result = asyncio.run(Toolbox.work_python(context, WorkPython(code='open("/output/dados.csv", "w").write("a,b\\n1,2\\n")')))
    assert result['exit_code'] == 0, result
    assert result['artifacts'] == context.run.artifacts
    assert result['artifacts'][0]['url'] == '/api/artifacts/test'


def test_work_files_limits_and_extension():
    import pytest
    from tools.work_files import WorkFiles, MAX_BYTES
    files = WorkFiles()
    with pytest.raises(PermissionError):
        files.write('/danger.html', b'x')
    with pytest.raises(OSError):
        files.write('/large.csv', b'x' * (MAX_BYTES + 1))


def test_failed_write_does_not_publish(tmp_path):
    from types import SimpleNamespace
    context = SimpleNamespace(run=SimpleNamespace(id='run', artifacts=[]), store=SimpleNamespace(artifacts_dir=tmp_path))
    code = 'try:\n open("/output/test.html", "w").write("x")\nexcept OSError:\n pass'
    result = asyncio.run(Toolbox.work_python(context, WorkPython(code=code)))
    assert result['file_error'] and result['artifacts'] == []


def test_work_zip_round_trip(tmp_path):
    import zipfile
    from types import SimpleNamespace
    class Store:
        artifacts_dir = tmp_path
        def save_artifact(self, run_id, title, extension, content):
            (tmp_path / 'artifact.zip').write_bytes(content)
            return {'filename': 'artifact.zip', 'title': title}
    context = SimpleNamespace(run=SimpleNamespace(id='run', artifacts=[]), store=Store())
    code = 'import zipfile\nwith zipfile.ZipFile("/output/result.zip", "w") as f:\n f.writestr("dados.txt", "conteudo")'
    result = asyncio.run(Toolbox.work_python(context, WorkPython(code=code)))
    assert result['exit_code'] == 0 and len(result['artifacts']) == 1
    with zipfile.ZipFile(tmp_path / 'artifact.zip') as archive:
        assert archive.testzip() is None
        assert archive.read('dados.txt') == b'conteudo'
