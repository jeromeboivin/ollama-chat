"""Tests for file operation functions (read_file, create_file, delete_file, expand_env_vars, run_command)."""
import os
import pytest
from unittest.mock import patch
import ollama_chat as oc
from ollama_chat_lib import state


class TestReadFile:

    def test_read_existing_file(self, reset_globals, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello world", encoding="utf-8")
        result = oc.read_file(str(f))
        assert result == "hello world"

    def test_read_nonexistent_file(self, reset_globals):
        result = oc.read_file("/tmp/nonexistent_file_abc123.txt")
        assert "Error" in result
        assert "does not exist" in result

    def test_read_directory_not_file(self, reset_globals, tmp_path):
        result = oc.read_file(str(tmp_path))
        assert "Error" in result
        assert "is not a file" in result

    def test_read_with_encoding(self, reset_globals, tmp_path):
        f = tmp_path / "latin.txt"
        f.write_text("café", encoding="latin-1")
        result = oc.read_file(str(f), encoding="latin-1")
        assert result == "café"

    def test_read_verbose_mode(self, reset_globals, tmp_path):
        f = tmp_path / "v.txt"
        f.write_text("data", encoding="utf-8")
        state.verbose_mode = True
        state.plugins = []
        result = oc.read_file(str(f))
        assert result == "data"


class TestCreateFile:

    def test_create_new_file(self, reset_globals, tmp_path):
        state.session_created_files = []
        fp = str(tmp_path / "new.txt")
        result = oc.create_file(fp, "content")
        assert "successfully" in result.lower()
        assert os.path.exists(fp)
        with open(fp, encoding="utf-8") as fh:
            assert fh.read() == "content"
        assert fp in state.session_created_files

    def test_create_with_parent_dirs(self, reset_globals, tmp_path):
        state.session_created_files = []
        fp = str(tmp_path / "a" / "b" / "c.txt")
        result = oc.create_file(fp, "nested")
        assert "successfully" in result.lower()
        assert os.path.exists(fp)

    def test_create_tracks_only_once(self, reset_globals, tmp_path):
        state.session_created_files = []
        fp = str(tmp_path / "dup.txt")
        oc.create_file(fp, "v1")
        oc.create_file(fp, "v2")
        assert state.session_created_files.count(fp) == 1


class TestDeleteFile:

    def test_delete_session_file(self, reset_globals, tmp_path):
        state.session_created_files = []
        fp = str(tmp_path / "del.txt")
        oc.create_file(fp, "bye")
        result = oc.delete_file(fp)
        assert "successfully" in result.lower()
        assert not os.path.exists(fp)
        assert fp not in state.session_created_files

    def test_delete_non_session_file(self, reset_globals, tmp_path):
        state.session_created_files = []
        fp = str(tmp_path / "foreign.txt")
        with open(fp, "w") as fh:
            fh.write("x")
        result = oc.delete_file(fp)
        assert "Error" in result
        assert os.path.exists(fp)

    def test_delete_already_removed(self, reset_globals, tmp_path):
        state.session_created_files = []
        fp = str(tmp_path / "gone.txt")
        oc.create_file(fp, "temp")
        os.remove(fp)  # remove outside the API
        result = oc.delete_file(fp)
        assert "already deleted" in result.lower() or "does not exist" in result.lower()
        assert fp not in state.session_created_files


class TestExpandEnvVars:

    def test_expand_home(self, reset_globals):
        with patch.dict(os.environ, {"MY_TEST_VAR": "hello"}):
            result = oc.expand_env_vars("$MY_TEST_VAR/path")
        assert result == "hello/path"

    def test_no_vars(self, reset_globals):
        result = oc.expand_env_vars("plain_text")
        assert result == "plain_text"


class TestRunCommand:

    def test_simple_command(self, reset_globals):
        stdout, stderr = oc.run_command("echo hello")
        assert "hello" in stdout

    def test_failing_command(self, reset_globals):
        stdout, stderr = oc.run_command("ls /nonexistent_dir_abc123")
        assert stderr  # should have error output
