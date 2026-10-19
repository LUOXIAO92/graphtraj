"""Administrative adoption over the installed proxy and an isolated native socket."""
import asyncio
import json
import os
from pathlib import Path
import shutil
import tempfile

import pytest
from conftest import InstalledCommands


@pytest.mark.parametrize('observe_only', [False, True])
@pytest.mark.parametrize('response_mode', ['structured', 'text', 'tool-error', 'unknown-wrapper', 'rpc-error'])
def test_installed_proxy_uses_websocket_for_public_refresh(
    tmp_path: Path, observe_only: bool, installed_commands: InstalledCommands,
    response_mode: str,
) -> None:
    """The real proxy carries Upgrade and framed RPCs, without a real host or model."""
    from websockets.asyncio.server import unix_serve

    if shutil.which('codex') is None:
        pytest.skip('Installed Codex proxy required for the real transport boundary')
    requests = []

    async def handle(connection) -> None:
        """Serve only the public metadata and MCP methods in the fixed operation."""
        from websockets.exceptions import ConnectionClosed

        assert connection.request.path == '/rpc'
        while True:
            try:
                payload = await connection.recv()
            except ConnectionClosed:
                return
            request = json.loads(payload)
            requests.append(request)
            method, params = request['method'], request.get('params')
            if method == 'initialized':
                continue
            result = {}
            if method == 'thread/read':
                assert params == {'threadId': 'current-main', 'includeTurns': False}
                result = {'thread': {'id': 'current-main', 'cwd': str(tmp_path),
                                    'source': 'appServer', 'status': {'type': 'active'}}}
            elif method == 'config/mcpServer/reload':
                assert params is None
            elif method == 'mcpServerStatus/list':
                assert params == {'threadId': 'current-main', 'serverName': 'graphtraj',
                                  'detail': 'toolsAndAuthOnly'}
                result = {'data': [{'name': 'graphtraj', 'tools': {'agents': {}, 'tasks': {}},
                                    'runtimeStatus': 'connected'}], 'nextCursor': None}
            elif method == 'mcpServer/tool/call':
                assert params == {'threadId': 'current-main', 'server': 'graphtraj', 'tool': 'tasks',
                                  'arguments': {'action': 'discover'}, '_meta': {'threadId': 'current-main'}}
                result = {'content': [], 'structuredContent': {
                    'service': {'mcp': {'sha256': 'still-old-code', 'token': 'DO-NOT-DISCLOSE'}},
                    'features': [{'private': 'DO-NOT-DISCLOSE'}]}}
                if response_mode == 'text':
                    import yaml

                    result = {'content': [{'type': 'text', 'text': yaml.safe_dump(result['structuredContent'])}]}
                elif response_mode == 'tool-error':
                    result = {'content': [{'type': 'text', 'text': 'Native discovery refused; Bearer secret-credential'}],
                              'isError': True}
                elif response_mode == 'unknown-wrapper':
                    result = {'content': [], 'structuredContent': {'result': result['structuredContent']}}
                elif response_mode == 'rpc-error':
                    await connection.send(json.dumps({'id': request['id'], 'error': {
                        'code': -32603, 'message': 'Native transport failed; Bearer secret-credential',
                        'data': {'private_body': 'DO-NOT-DISCLOSE'}}}))
                    continue
            await connection.send(json.dumps({'id': request['id'], 'result': result}))

    async def check() -> None:
        """Keep the short Unix socket private; no production socket is discovered."""
        with tempfile.TemporaryDirectory(prefix='g337-proxy-', dir='/private/tmp') as temporary:
            socket = Path(temporary) / 'control.sock'
            environment = {**os.environ, 'CODEX_HOME': str(Path(temporary) / 'empty-home')}
            environment.pop('PYTHONPATH', None)
            async with unix_serve(handle, str(socket)):
                command = [str(installed_commands.product), 'refresh-mcp',
                           '--socket', str(socket), '--main-session', 'current-main']
                if observe_only:
                    command.append('--observe-only')
                process = await asyncio.create_subprocess_exec(*command, cwd=tmp_path, env=environment,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                try:
                    output, error = await asyncio.wait_for(process.communicate(), 15)
                finally:
                    if process.returncode is None:
                        process.terminate()
                        await process.wait()
                success = response_mode in {'structured', 'text'}
                assert process.returncode == (0 if success else 1), error.decode()
                import yaml

                report = yaml.safe_load(output)
                assert report['main_session'] == 'current-main'
                assert report['evidence_available'] is success
                if success:
                    assert report['service']['mcp']['sha256'] == 'still-old-code'
                    assert report['discovery']['service_source'] == ('structuredContent' if response_mode == 'structured' else 'content[0].text')
                elif response_mode == 'tool-error':
                    assert report['discovery']['isError'] is True
                    assert 'Native discovery refused' in str(report['discovery']['errors'])
                elif response_mode == 'unknown-wrapper':
                    assert report['discovery']['structured_fields'] == ['result']
                    assert report['discovery']['structured_children']['result'] == ['features', 'service']
                else:
                    assert 'Native transport failed' in report['discovery']['rpc_error']['message']
                    assert report['discovery']['rpc_error']['code'] == -32603
                assert 'DO-NOT-DISCLOSE' not in output.decode()
                assert 'secret-credential' not in output.decode()
                assert report['reload_requested'] is not observe_only
                assert 'adopted' not in report and 'features' not in report
                assert report['servers'][0]['tools'] == ['agents', 'tasks']

    asyncio.run(check())
    assert [item['method'] for item in requests] == [
        'initialize', 'initialized', 'thread/read',
        *([] if observe_only else ['config/mcpServer/reload']),
        'mcpServerStatus/list', 'mcpServer/tool/call',
    ]


def test_installed_proxy_does_not_convert_json_lines_to_websocket(tmp_path: Path) -> None:
    """The installed proxy forwards a raw JSON line unchanged, not as an Upgrade."""
    if shutil.which('codex') is None:
        pytest.skip('Installed Codex proxy required')

    async def check() -> None:
        """Capture only a synthetic initialize line on our own Unix endpoint."""
        received = asyncio.get_running_loop().create_future()

        async def capture(reader, writer) -> None:
            """Expose the proxy's actual first bytes without pretending to be a host."""
            received.set_result(await reader.readline())
            writer.close()
            await writer.wait_closed()

        with tempfile.TemporaryDirectory(prefix='g337-raw-', dir='/private/tmp') as temporary:
            socket = Path(temporary) / 'control.sock'
            async with await asyncio.start_unix_server(capture, path=str(socket)):
                process = await asyncio.create_subprocess_exec('codex', 'app-server', 'proxy', '--sock', str(socket),
                    env={**os.environ, 'CODEX_HOME': str(Path(temporary) / 'empty-home')},
                    stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                line = b'{"id":1,"method":"initialize","params":{}}\n'
                try:
                    process.stdin.write(line)
                    await process.stdin.drain()
                    assert await asyncio.wait_for(received, 5) == line
                finally:
                    if process.returncode is None:
                        process.terminate()
                    await process.communicate()

    asyncio.run(check())
