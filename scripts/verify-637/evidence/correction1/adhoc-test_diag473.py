"""Ad hoc check (not committed): a Codex child that cannot start names its cause in the 473 test's message."""
import pytest
import test_codex_child_interpreter_shutdown_473 as shutdown
from test_codex_tool_reclaim_462 import native_settings  # noqa: F401 (fixture)


def test_message_names_the_cause(tmp_path, native_settings):
    native_settings['adapter_request']['arguments'] = [str(tmp_path / 'no-such-codex')]
    with pytest.raises(AssertionError) as raised:
        shutdown.test_child_ends_completed_after_the_owner_main_thread_returns(tmp_path, native_settings)
    print('MESSAGE:', str(raised.value)[:1500])
    assert 'the peer did not start the tool; owner exit' in str(raised.value)
    assert '"state": "ended"' in str(raised.value) and '"error": {' in str(raised.value)
