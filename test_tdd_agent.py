import os
import pytest
from unittest.mock import patch, MagicMock
import subprocess

from tdd_agent import extract_code, get_prompt, append_new_test, run_tests

def test_extract_code_with_markdown():
    text = "Here is the code:\n```typescript\nconst x = 1;\n```\nDone."
    assert extract_code(text) == "const x = 1;"

def test_extract_code_with_tsx():
    text = "```tsx\n<div>Hello</div>\n```"
    assert extract_code(text) == "<div>Hello</div>"

def test_extract_code_without_markdown():
    text = "const y = 2;"
    assert extract_code(text) == "const y = 2;"

def test_get_prompt():
    source = "function add(a, b) { return a + b; }"
    test_code = "test('add', () => {});"
    prompt = get_prompt(source, test_code)
    
    assert source in prompt
    assert test_code in prompt
    assert "You are an expert Test-Driven Development" in prompt
    assert "exactly ONE new unit test" in prompt

def test_append_new_test_with_describe_block(tmp_path):
    # Setup a mock file with a describe block
    test_file = tmp_path / "test_file.ts"
    original_content = "describe('my suite', () => {\n  it('does A', () => {});\n});\n"
    test_file.write_text(original_content)
    
    new_test_content = '  it("does B", () => {});'
    append_new_test(str(test_file), new_test_content)
    
    result = test_file.read_text()
    
    # The new test should be inserted BEFORE the final `});`
    assert new_test_content in result
    assert result.endswith("});\n")

def test_append_new_test_without_describe_block(tmp_path):
    # Setup a mock file with plain top-level tests (no describe wrapper)
    test_file = tmp_path / "test_file.ts"
    original_content = "test('does A', () => {});\n"
    test_file.write_text(original_content)
    
    new_test_content = 'test("does B", () => {});'
    append_new_test(str(test_file), new_test_content)
    
    result = test_file.read_text()
    
    # Should simply append to the end
    assert new_test_content in result
    assert result.strip().endswith(new_test_content)

@patch("tdd_agent.subprocess.Popen")
def test_run_tests(mock_popen):
    # Setup mock process
    mock_process = MagicMock()
    # Simulate process stdout
    mock_process.stdout = ["Running tests...\n", "Test 1 failed\n"]
    mock_process.returncode = 1 # Failed
    mock_popen.return_value = mock_process
    
    failed, output = run_tests("fake_test_file.ts")
    
    assert failed is True
    assert "Running tests..." in output
    assert "Test 1 failed" in output
    
    # Verify Popen was called correctly with CI=true env
    mock_popen.assert_called_once()
    called_args, called_kwargs = mock_popen.call_args
    assert called_args[0] == ["npm", "test", "fake_test_file.ts"]
    assert called_kwargs["env"]["CI"] == "true"

@patch("tdd_agent.subprocess.Popen")
def test_run_tests_passing(mock_popen):
    mock_process = MagicMock()
    mock_process.stdout = ["All tests passed\n"]
    mock_process.returncode = 0 # Success
    mock_popen.return_value = mock_process
    
    failed, output = run_tests("fake_test_file.ts")
    
    assert failed is False
    assert "All tests passed" in output
