# Copyright 2021 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Tests for running fuzzers."""
import os
import sys
import tempfile
import unittest
from unittest import mock

import parameterized

import config_utils
import fuzz_target
import run_fuzzers

# pylint: disable=wrong-import-position
INFRA_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(INFRA_DIR)

import test_helpers

# NOTE: This integration test relies on
# https://github.com/google/oss-fuzz/tree/master/projects/example project.
EXAMPLE_PROJECT = 'example'

# Location of files used for testing.
TEST_FILES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               'test_files')

MEMORY_FUZZER_DIR = os.path.join(TEST_FILES_PATH, 'memory')
MEMORY_FUZZER = 'curl_fuzzer_memory'

UNDEFINED_FUZZER_DIR = os.path.join(TEST_FILES_PATH, 'undefined')
UNDEFINED_FUZZER = 'curl_fuzzer_undefined'

FUZZ_SECONDS = 10


def _create_config(**kwargs):
  """Creates a config object and then sets every attribute that is a key in
  |kwargs| to the corresponding value. Asserts that each key in |kwargs| is an
  attribute of Config."""
  with mock.patch('os.path.basename', return_value=None), mock.patch(
      'config_utils.get_project_src_path',
      return_value=None), mock.patch('config_utils._is_dry_run',
                                     return_value=True):
    config = config_utils.RunFuzzersConfig()

  for key, value in kwargs.items():
    assert hasattr(config, key), 'Config doesn\'t have attribute: ' + key
    setattr(config, key, value)
  return config


class RunFuzzerIntegrationTestMixin:  # pylint: disable=too-few-public-methods,invalid-name
  """Mixin for integration test classes that runbuild_fuzzers on builds of a
  specific sanitizer."""
  # These must be defined by children.
  FUZZER_DIR = None
  FUZZER = None

  def _test_run_with_sanitizer(self, fuzzer_dir, sanitizer):
    """Calls run_fuzzers on fuzzer_dir and |sanitizer| and asserts
    the run succeeded and that no bug was found."""
    with test_helpers.temp_dir_copy(fuzzer_dir) as fuzzer_dir_copy:
      config = _create_config(fuzz_seconds=FUZZ_SECONDS,
                              workspace=fuzzer_dir_copy,
                              project_name='curl',
                              sanitizer=sanitizer)
      run_success, bug_found = run_fuzzers.run_fuzzers(config)
    self.assertTrue(run_success)
    self.assertFalse(bug_found)


class RunMemoryFuzzerIntegrationTest(RunFuzzerIntegrationTestMixin,
                                     unittest.TestCase):
  """Integration test for build_fuzzers with an MSAN build."""
  FUZZER_DIR = MEMORY_FUZZER_DIR
  FUZZER = MEMORY_FUZZER

  @unittest.skipIf(not os.getenv('INTEGRATION_TESTS'),
                   'INTEGRATION_TESTS=1 not set')
  def test_run_with_memory_sanitizer(self):
    """Tests run_fuzzers with a valid MSAN build."""
    self._test_run_with_sanitizer(self.FUZZER_DIR, 'memory')


class RunUndefinedFuzzerIntegrationTest(RunFuzzerIntegrationTestMixin,
                                        unittest.TestCase):
  """Integration test for build_fuzzers with an UBSAN build."""
  FUZZER_DIR = UNDEFINED_FUZZER_DIR
  FUZZER = UNDEFINED_FUZZER

  @unittest.skipIf(not os.getenv('INTEGRATION_TESTS'),
                   'INTEGRATION_TESTS=1 not set')
  def test_run_with_undefined_sanitizer(self):
    """Tests run_fuzzers with a valid UBSAN build."""
    self._test_run_with_sanitizer(self.FUZZER_DIR, 'undefined')


class BaseFuzzTargetRunnerTest(unittest.TestCase):
  """Tests BaseFuzzTargetRunner."""

  def _create_runner(self, **kwargs):  # pylint: disable=no-self-use
    defaults = {
        'fuzz_seconds': FUZZ_SECONDS,
        'project_name': EXAMPLE_PROJECT
    }
    for default_key, default_value in defaults.items():
      if default_key not in kwargs:
        kwargs[default_key] = default_value

    config = _create_config(**kwargs)
    return run_fuzzers.BaseFuzzTargetRunner(config)

  def _test_initialize_fail(self, expected_error_args, **create_runner_kwargs):
    with mock.patch('logging.error') as mocked_error:
      runner = self._create_runner(**create_runner_kwargs)
      self.assertFalse(runner.initialize())
      mocked_error.assert_called_with(*expected_error_args)

  @parameterized.parameterized.expand([(0,), (None,), (-1,)])
  def test_initialize_invalid_fuzz_seconds(self, fuzz_seconds):
    """Tests initialize fails with an invalid fuzz seconds."""
    expected_error_args = ('Fuzz_seconds argument must be greater than 1, '
                            'but was: %s.', fuzz_seconds)
    with tempfile.TemporaryDirectory() as tmp_dir:
      out_path = os.path.join(tmp_dir, 'out')
      os.mkdir(out_path)
      with mock.patch('utils.get_fuzz_targets') as mocked_get_fuzz_targets:
        mocked_get_fuzz_targets.return_value = [
            os.path.join(out_path, 'fuzz_target')
        ]
        self._test_initialize_fail(expected_error_args,
                                   fuzz_seconds=fuzz_seconds,
                                   workspace=tmp_dir)

  def test_initialize_no_out_dir(self):
    """Tests initialize fails with no out dir."""
    with tempfile.TemporaryDirectory() as tmp_dir:
      out_path = os.path.join(tmp_dir, 'out')
      expected_error_args = ('Out directory: %s does not exist.', out_path)
      self._test_initialize_fail(expected_error_args, workspace=tmp_dir)

  def test_initialize_nonempty_artifacts(self):
    """Tests initialize with a file artifacts path."""
    with tempfile.TemporaryDirectory() as tmp_dir:
      out_path = os.path.join(tmp_dir, 'out')
      os.mkdir(out_path)
      artifacts_path = os.path.join(out_path, 'artifacts')
      with open(artifacts_path, 'w') as artifacts_handle:
        artifacts_handle.write('fake')
      expected_error_args = ('Artifacts path: %s is not an empty directory.',
                             artifacts_path)
      self._test_initialize_fail(expected_error_args, workspace=tmp_dir)

  def test_initialize_bad_artifacts(self):
    """Tests initialize with a non-empty artifacts path."""
    with tempfile.TemporaryDirectory() as tmp_dir:
      out_path = os.path.join(tmp_dir, 'out')
      artifacts_path = os.path.join(out_path, 'artifacts')
      os.makedirs(artifacts_path)
      artifact_path = os.path.join(artifacts_path, 'artifact')
      with open(artifact_path, 'w') as artifact_handle:
        artifact_handle.write('fake')
      expected_error_args = (
          'Artifacts path: %s is not an empty directory.', artifacts_path)
      self._test_initialize_fail(expected_error_args, workspace=tmp_dir)

  @mock.patch('utils.get_fuzz_targets')
  @mock.patch('logging.error')
  def test_initialize_empty_artifacts(self, mocked_log_error,
                                      mocked_get_fuzz_targets):
    """Tests initialize with an empty artifacts dir."""
    mocked_get_fuzz_targets.return_value = ['fuzz-target']
    with tempfile.TemporaryDirectory() as tmp_dir:
      out_path = os.path.join(tmp_dir, 'out')
      artifacts_path = os.path.join(out_path, 'artifacts')
      os.makedirs(artifacts_path)
      runner = self._create_runner(workspace=tmp_dir)
      self.assertTrue(runner.initialize())
      mocked_log_error.assert_not_called()
      self.assertTrue(os.path.isdir(artifacts_path))

  @mock.patch('utils.get_fuzz_targets')
  @mock.patch('logging.error')
  def test_initialize_no_artifacts(self, mocked_log_error,
                                   mocked_get_fuzz_targets):
    """Tests initialize with a no artifacts dir (the expected setting)."""
    mocked_get_fuzz_targets.return_value = ['fuzz-target']
    with tempfile.TemporaryDirectory() as tmp_dir:
      out_path = os.path.join(tmp_dir, 'out')
      os.makedirs(out_path)
      runner = self._create_runner(workspace=tmp_dir)
      self.assertTrue(runner.initialize())
      mocked_log_error.assert_not_called()
      self.assertTrue(os.path.isdir(os.path.join(out_path, 'artifacts')))


class RunAddressFuzzersIntegrationTest(RunFuzzerIntegrationTestMixin,
                                       unittest.TestCase):
  """Integration tests for build_fuzzers with an ASAN build."""

  @unittest.skipIf(not os.getenv('INTEGRATION_TESTS'),
                   'INTEGRATION_TESTS=1 not set')
  def test_new_bug_found(self):
    """Tests run_fuzzers with a valid ASAN build."""
    # Set the first return value to True, then the second to False to
    # emulate a bug existing in the current PR but not on the downloaded
    # OSS-Fuzz build.
    with mock.patch.object(fuzz_target.FuzzTarget,
                           'is_reproducible',
                           side_effect=[True, False]):
      config = _create_config(fuzz_seconds=FUZZ_SECONDS,
                              workspace=TEST_FILES_PATH,
                              project_name=EXAMPLE_PROJECT)
      run_success, bug_found = run_fuzzers.run_fuzzers(config)
      build_dir = os.path.join(TEST_FILES_PATH, 'out', 'oss_fuzz_latest')
      self.assertTrue(os.path.exists(build_dir))
      self.assertNotEqual(0, len(os.listdir(build_dir)))
      self.assertTrue(run_success)
      self.assertTrue(bug_found)

  @unittest.skipIf(not os.getenv('INTEGRATION_TESTS'),
                   'INTEGRATION_TESTS=1 not set')
  def test_old_bug_found(self):
    """Tests run_fuzzers with a bug found in OSS-Fuzz before."""
    config = _create_config(fuzz_seconds=FUZZ_SECONDS,
                            workspace=TEST_FILES_PATH,
                            project_name=EXAMPLE_PROJECT)
    with mock.patch.object(fuzz_target.FuzzTarget,
                           'is_reproducible',
                           side_effect=[True, True]):
      config = _create_config(fuzz_seconds=FUZZ_SECONDS,
                              workspace=TEST_FILES_PATH,
                              project_name=EXAMPLE_PROJECT)
      run_success, bug_found = run_fuzzers.run_fuzzers(config)
      build_dir = os.path.join(TEST_FILES_PATH, 'out', 'oss_fuzz_latest')
      self.assertTrue(os.path.exists(build_dir))
      self.assertNotEqual(0, len(os.listdir(build_dir)))
      self.assertTrue(run_success)
      self.assertFalse(bug_found)

  def test_invalid_build(self):
    """Tests run_fuzzers with an invalid ASAN build."""
    with tempfile.TemporaryDirectory() as tmp_dir:
      out_path = os.path.join(tmp_dir, 'out')
      os.mkdir(out_path)
      config = _create_config(fuzz_seconds=FUZZ_SECONDS,
                              workspace=tmp_dir,
                              project_name=EXAMPLE_PROJECT)
      run_success, bug_found = run_fuzzers.run_fuzzers(config)
    self.assertFalse(run_success)
    self.assertFalse(bug_found)


if __name__ == '__main__':
  unittest.main()
