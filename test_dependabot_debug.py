import pytest
from unittest.mock import patch, MagicMock
from dependabot_debug import extract_bash, get_job_logs, run_bash_script

def test_extract_bash_with_markdown():
    text = "Here is the script:\n```bash\necho 'hello'\n```\nDone."
    assert extract_bash(text) == "echo 'hello'"

def test_extract_bash_with_sh():
    text = "```sh\nls -la\n```"
    assert extract_bash(text) == "ls -la"

def test_extract_bash_without_markdown():
    text = "echo 'hello'"
    assert extract_bash(text) == ""

@patch("dependabot_debug.requests.get")
def test_get_job_logs_success(mock_get):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = "log content"
    mock_get.return_value = mock_response

    logs = get_job_logs("fake_token", "recharts/recharts", 12345)
    
    assert logs == "log content"
    mock_get.assert_called_once()
    args, kwargs = mock_get.call_args
    assert args[0] == "https://api.github.com/repos/recharts/recharts/actions/jobs/12345/logs"
    assert kwargs["headers"]["Authorization"] == "Bearer fake_token"

@patch("dependabot_debug.requests.get")
def test_get_job_logs_failure(mock_get):
    mock_response = MagicMock()
    mock_response.status_code = 404
    mock_response.text = "Not found"
    mock_get.return_value = mock_response

    logs = get_job_logs("fake_token", "recharts/recharts", 12345)
    
    assert logs == ""

@patch("dependabot_debug.subprocess.Popen")
def test_run_bash_script(mock_popen):
    mock_process = MagicMock()
    mock_process.communicate.return_value = ("output content", None)
    mock_process.returncode = 0
    mock_popen.return_value = mock_process

    retcode, stdout = run_bash_script("echo 'hello'", "/fake/cwd")
    
    assert retcode == 0
    assert stdout == "output content"
    mock_popen.assert_called_once()
    args, kwargs = mock_popen.call_args
    assert args[0] == ["bash", "-c", "echo 'hello'"]
    assert kwargs["cwd"] == "/fake/cwd"

