# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

# pyre-unsafe

import unittest

from aioresponses import aioresponses
from github.WorkflowJob import WorkflowJob

from kernel_patches_daemon.github_logs import (
    BpfGithubLogExtractor,
    DefaultGithubLogExtractor,
    GithubFailedJobLog,
    LinuxBlockGithubLogExtractor,
)

from . import read_fixture


class MockWorkflowJob(WorkflowJob):
    """Pretty hacky mock object where we only override the fields the code uses"""

    def __init__(self, name: str, conclusion: str, logs_url: str, html_url: str):
        self.__name: str = name
        self.__conclusion: str = conclusion
        self.__logs_url: str = logs_url
        self.__html_url: str = html_url

    @property
    def name(self) -> str:
        return self.__name

    @property
    def conclusion(self) -> str:
        return self.__conclusion

    def logs_url(self) -> str:
        return self.__logs_url

    @property
    def html_url(self) -> str:
        return self.__html_url


class TestBpfGithubLogs(unittest.IsolatedAsyncioTestCase):
    # Always show full diff on string match failures
    maxDiff = None

    @aioresponses()
    async def test_extract_some_failures(self, mocked: aioresponses):
        mocked.get("job1.com", status=200, body="job1")
        mocked.get("job2.com", status=200, body="job2")
        mocked.get("job3.com", status=200, body="job3")

        jobs = [
            MockWorkflowJob(
                "x86_64-gcc / test / suite1 on x86_64 with gcc",
                "failure",
                "job1.com",
                "https://job1.com",
            ),
            MockWorkflowJob(
                "aarch64-gcc / test / suite2 on aarch64 with gcc",
                "success",
                "job2.com",
                "https://job2.com",
            ),
            MockWorkflowJob(
                "s390x-llvm-17 / test / suite3 on s390x with llvm-17",
                "failure",
                "job3.com",
                "https://job3.com",
            ),
        ]

        extractor = BpfGithubLogExtractor()
        logs = await extractor.extract_failed_logs(jobs)

        self.assertEqual(len(logs), 2)
        self.assertEqual(logs[0].suite, "suite1")
        self.assertEqual(logs[0].arch, "x86_64")
        self.assertEqual(logs[0].compiler, "gcc")
        self.assertEqual(logs[0].log, "job1")
        self.assertEqual(logs[1].suite, "suite3")
        self.assertEqual(logs[1].arch, "s390x")
        self.assertEqual(logs[1].compiler, "llvm-17")
        self.assertEqual(logs[1].log, "job3")

    @aioresponses()
    async def test_extract_none(self, mocked: aioresponses):
        mocked.get("job1.com", status=200, body="job1")
        mocked.get("job2.com", status=200, body="job2")

        jobs = [
            MockWorkflowJob(
                "x86_64-gcc / test / suite1 on x86_64 with gcc",
                "pending",
                "job1.com",
                "https://job2.com",
            ),
            MockWorkflowJob(
                "aarch64-gcc / build / suite2 on aarch64 with gcc",
                "success",
                "job2.com",
                "https://job2.com",
            ),
        ]

        extractor = BpfGithubLogExtractor()
        logs = await extractor.extract_failed_logs(jobs)
        self.assertEqual(len(logs), 0)

    @aioresponses()
    async def test_extract_partial_invalid_names(self, mocked: aioresponses):
        mocked.get("job1.com", status=200, body="job1")
        mocked.get("job2.com", status=200, body="job2")

        jobs = [
            MockWorkflowJob(
                "valid / valid / suite1 zzz x86_64 with gcc",
                "failure",
                "job1.com",
                "https://job1.com",
            ),
            MockWorkflowJob(
                "valid / valid / build for aarch64 with gcc",
                "failure",
                "job2.com",
                "https://job2.com",
            ),
        ]

        extractor = BpfGithubLogExtractor()
        logs = await extractor.extract_failed_logs(jobs)
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0].suite, "build")
        self.assertEqual(logs[0].arch, "aarch64")
        self.assertEqual(logs[0].compiler, "gcc")

    @aioresponses()
    async def test_extract_invalid_names_no_error(self, mocked: aioresponses):
        mocked.get("job1.com", status=200, body="job1")
        mocked.get("job2.com", status=200, body="job2")

        jobs = [
            MockWorkflowJob(
                "valid / valid / zzzzzzzzz", "pending", "job1.com", "https://job1.com"
            ),
            MockWorkflowJob(
                "valid / valid / this is-not a valid job",
                "success",
                "job2.com",
                "https://job2.com",
            ),
        ]

        extractor = BpfGithubLogExtractor()
        logs = await extractor.extract_failed_logs(jobs)

        # None of the jobs should have parsed. We expect no errors regardless.
        self.assertEqual(len(logs), 0)

    @aioresponses()
    async def test_extract_names_no_matrix(self, mocked: aioresponses):
        """
        This tests the case where somehow the matrix parameters are removed.
        In case github does something funny or the overall matrix configuration is changed.
        """
        mocked.get("job1.com", status=200, body="job1")
        mocked.get("job2.com", status=200, body="job2")
        mocked.get("job3.com", status=200, body="job3")

        jobs = [
            MockWorkflowJob(
                "suite1 on x86_64 with gcc", "failure", "job1.com", "https://job1.com"
            ),
            MockWorkflowJob(
                "suite3 on s390x with llvm-17",
                "failure",
                "job3.com",
                "https://job3.com",
            ),
        ]

        extractor = BpfGithubLogExtractor()
        logs = await extractor.extract_failed_logs(jobs)

        self.assertEqual(len(logs), 2)
        self.assertEqual(logs[0].suite, "suite1")
        self.assertEqual(logs[0].arch, "x86_64")
        self.assertEqual(logs[0].compiler, "gcc")
        self.assertEqual(logs[0].log, "job1")
        self.assertEqual(logs[1].suite, "suite3")
        self.assertEqual(logs[1].arch, "s390x")
        self.assertEqual(logs[1].compiler, "llvm-17")
        self.assertEqual(logs[1].log, "job3")

    def test_inline_email_text_none(self):
        input = read_fixture("job_log_no_failures")
        expected = read_fixture("test_inline_email_text_none.golden")

        extractor = BpfGithubLogExtractor()
        output = extractor.generate_inline_email_text(
            [
                GithubFailedJobLog(
                    suite="test_progs",
                    arch="x86_64",
                    compiler="llvm-17",
                    log=input,
                    url="https://job1.com",
                )
            ]
        )

        self.assertEqual(expected, output)

    def test_inline_email_text_single(self):
        input = read_fixture("job_log_two_failures")
        expected = read_fixture("test_inline_email_text_single.golden")

        extractor = BpfGithubLogExtractor()
        output = extractor.generate_inline_email_text(
            [
                GithubFailedJobLog(
                    suite="test_progs",
                    arch="x86_64",
                    compiler="gcc",
                    log=input,
                    url="https://job1.com",
                )
            ]
        )

        self.assertEqual(expected, output)

    def test_inline_email_text_multiple(self):
        input1 = read_fixture("job_log_two_failures")
        input2 = read_fixture("job_log_one_failure")
        expected = read_fixture("test_inline_email_text_multiple.golden")

        extractor = BpfGithubLogExtractor()
        output = extractor.generate_inline_email_text(
            [
                GithubFailedJobLog(
                    suite="test_progs",
                    arch="x86_64",
                    compiler="gcc",
                    log=input1,
                    url="https://job1.com",
                ),
                GithubFailedJobLog(
                    suite="test_progs_no_alu32",
                    arch="x86_64",
                    compiler="gcc",
                    log=input2,
                    url="https://job2.com",
                ),
            ]
        )

        self.assertEqual(expected, output)


class TestLinuxBlockGithubLogs(unittest.TestCase):
    def setUp(self) -> None:
        self.extractor = LinuxBlockGithubLogExtractor(certificate_path="")

    def _log(self, lines):
        return GithubFailedJobLog(
            suite="None",
            arch="None",
            compiler="None",
            log="\n".join(lines),
            url="https://github.com/o/r/actions/runs/1/job/2",
        )

    def _script_lines(self):
        return [
            '2026-11-08T09:49:50.8176794Z echo "KPD: blktests completed"',
            '2026-11-08T09:49:50.8176794Z test -f all_failures && echo "KPD: Failures:"',
            '2026-11-08T09:49:50.8176794Z test -f all_failures && echo "KPD: Failures end"',
        ]

    def test_failed_tests(self):
        log = self._log(
            self._script_lines()
            + [
                "2026-11-08T09:50:30.7063602Z KPD: blktests completed",
                "2026-11-08T09:50:31.7063602Z KPD: Failures:",
                "2026-11-08T09:50:32.7063602Z block/001 nvme/027",
                "2026-11-08T09:50:33.7063602Z ",
                "2026-11-08T09:50:34.7063602Z KPD: Failures end",
            ]
        )

        self.assertEqual(
            "\nFailed test cases: block/001 nvme/027\n",
            self.extractor.generate_inline_email_text([log]),
        )
        self.assertTrue(self.extractor.notify_submitter([log]))

    def test_completed_without_failed_tests(self):
        log = self._log(
            self._script_lines()
            + ["2026-11-08T09:50:30.7063602Z KPD: blktests completed"]
        )
        text = self.extractor.generate_inline_email_text([log])

        self.assertEqual(LinuxBlockGithubLogExtractor.EMAIL_TEXT_NO_FAILED_TESTS, text)
        self.assertFalse(self.extractor.notify_submitter([log]))
        self.assertNotIn("All test cases passed", text)

    def test_blktests_not_completed(self):
        log = self._log(self._script_lines())

        self.assertEqual(
            LinuxBlockGithubLogExtractor.EMAIL_TEXT_NOT_COMPLETED,
            self.extractor.generate_inline_email_text([log]),
        )
        self.assertFalse(self.extractor.notify_submitter([log]))

    def test_no_logs(self):
        self.assertEqual("", self.extractor.generate_inline_email_text([]))

    def test_failures_across_multiple_logs(self):
        completed_without_failures = self._log(
            ["2026-11-08T09:50:30.7063602Z KPD: blktests completed"]
        )
        with_failures = self._log(
            [
                "2026-11-08T09:50:30.7063602Z KPD: blktests completed",
                "2026-11-08T09:50:31.7063602Z KPD: Failures:",
                "2026-11-08T09:50:32.7063602Z block/001 nvme/027",
                "2026-11-08T09:50:33.7063602Z KPD: Failures end",
            ]
        )

        self.assertEqual(
            "\nFailed test cases: block/001 nvme/027\n",
            self.extractor.generate_inline_email_text(
                [completed_without_failures, with_failures]
            ),
        )
        self.assertTrue(
            self.extractor.notify_submitter([completed_without_failures, with_failures])
        )

    def test_default_extractor_notifies_submitter(self):
        log = self._log([])
        extractor = DefaultGithubLogExtractor(certificate_path="")

        self.assertTrue(extractor.notify_submitter([log]))
