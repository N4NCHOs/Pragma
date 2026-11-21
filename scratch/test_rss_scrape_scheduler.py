"""Run the approved offline pruning checks against the original scheduler.

Share the copy's article fixtures and saved-page replay so both schedulers are
held to the same extraction and RSS metadata contract. Scheduler flow checks use
temporary output paths; the original CLI/reset function is never called.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from scratch import test_rss_scrape_scheduler_pruned as pruning_checks


class OriginalArticleTests(pruning_checks.PrunedArticleTests):
    def setUp(self):
        target = patch.object(pruning_checks, "scraper", pruning_checks.original)
        target.start()
        self.addCleanup(target.stop)


class OriginalSchedulerFlowTests(unittest.TestCase):
    def setUp(self):
        target = patch.object(pruning_checks, "scraper", pruning_checks.original)
        target.start()
        self.addCleanup(target.stop)
        pruning_checks.SchedulerFlowTests.setUp(self)

    # Reuse only the incremental-flow checks. The copy's direct-reset test is
    # intentionally excluded because the original main() resets live outputs.
    test_one_session_rss_first_known_history_skipped_delay_and_checkpoints = (
        pruning_checks.SchedulerFlowTests
        .test_one_session_rss_first_known_history_skipped_delay_and_checkpoints
    )
    test_feed_error_does_not_advance_history = (
        pruning_checks.SchedulerFlowTests.test_feed_error_does_not_advance_history
    )


if __name__ == "__main__":
    unittest.main()
