"""
sentry.tsdb.inmemory
~~~~~~~~~~~~~~~~~~~~

:copyright: (c) 2010-2014 by the Sentry Team, see AUTHORS for more details.
:license: BSD, see LICENSE for more details.
"""
from __future__ import absolute_import

from collections import Counter, defaultdict

import six
from django.utils import timezone

from sentry.tsdb.base import BaseTSDB
from sentry.utils.dates import to_datetime, to_timestamp


class InMemoryTSDB(BaseTSDB):
    """
    An in-memory time-series storage.

    This should not be used in production as it will leak memory.
    """

    def __init__(self, *args, **kwargs):
        super(InMemoryTSDB, self).__init__(*args, **kwargs)
        self.flush()

    def incr(self, model, key, timestamp=None, count=1, environment=None):
        environments = set([environment, None])

        if timestamp is None:
            timestamp = timezone.now()

        for rollup, max_values in six.iteritems(self.rollups):
            norm_epoch = self.normalize_to_rollup(timestamp, rollup)
            for environment in environments:
                self.data[model][(key, environment)][norm_epoch] += count

    def merge(self, model, destination, sources, timestamp=None, environments=None):
        environments = (set(environments) if environments is not None else set()).union([None])
        raise NotImplementedError

        destination = self.data[model][destination]
        for source in sources:
            for bucket, count in self.data[model].pop(source, {}).items():
                destination[bucket] += count

    def delete(self, models, keys, start=None, end=None, timestamp=None, environments=None):
        environments = (set(environments) if environments is not None else set()).union([None])

        rollups = self.get_active_series(start, end, timestamp)

        for rollup, series in rollups.items():
            for model in models:
                for key in keys:
                    for environment in environments:
                        data = self.data[model][(key, environment)]
                        for timestamp in series:
                            data.pop(
                                self.normalize_to_rollup(timestamp, rollup),
                                0,
                            )

    def get_range(self, model, keys, start, end, rollup=None, environment=None):
        rollup, series = self.get_optimal_rollup_series(start, end, rollup)

        results = []
        for timestamp in map(to_datetime, series):
            norm_epoch = self.normalize_to_rollup(timestamp, rollup)

            for key in keys:
                value = self.data[model][(key, environment)][norm_epoch]
                results.append((to_timestamp(timestamp), key, value))

        results_by_key = defaultdict(dict)
        for epoch, key, count in results:
            results_by_key[key][epoch] = int(count or 0)

        for key, points in six.iteritems(results_by_key):
            results_by_key[key] = sorted(points.items())
        return dict(results_by_key)

    def record(self, model, key, values, timestamp=None, environment=None):
        environments = set([environment, None])

        if timestamp is None:
            timestamp = timezone.now()

        for rollup, max_values in six.iteritems(self.rollups):
            r = self.normalize_to_rollup(timestamp, rollup)
            for environment in environments:
                self.sets[model][(key, environment)][r].update(values)

    def get_distinct_counts_series(self, model, keys, start, end=None,
                                   rollup=None, environment=None):
        rollup, series = self.get_optimal_rollup_series(start, end, rollup)

        results = {}
        for key in keys:
            source = self.sets[model][(key, environment)]
            counts = results[key] = []
            for timestamp in series:
                r = self.normalize_ts_to_rollup(timestamp, rollup)
                counts.append((timestamp, len(source[r])))

        return results

    def get_distinct_counts_totals(self, model, keys, start, end=None,
                                   rollup=None, environment=None):
        rollup, series = self.get_optimal_rollup_series(start, end, rollup)

        results = {}
        for key in keys:
            source = self.sets[model][(key, environment)]
            values = set()
            for timestamp in series:
                r = self.normalize_ts_to_rollup(timestamp, rollup)
                values.update(source[r])
            results[key] = len(values)

        return results

    def get_distinct_counts_union(self, model, keys, start, end=None,
                                  rollup=None, environment=None):
        rollup, series = self.get_optimal_rollup_series(start, end, rollup)

        values = set()
        for key in keys:
            source = self.sets[model][(key, environment)]
            for timestamp in series:
                r = self.normalize_ts_to_rollup(timestamp, rollup)
                values.update(source[r])

        return len(values)

    def merge_distinct_counts(self, model, destination, sources, timestamp=None, environments=None):
        environments = (set(environments) if environments is not None else set()).union([None])
        raise NotImplementedError

        destination = self.sets[model][destination]
        for source in sources:
            for bucket, values in self.sets[model].pop(source, {}).items():
                destination[bucket].update(values)

    def delete_distinct_counts(self, models, keys, start=None, end=None,
                               timestamp=None, environments=None):
        environments = (set(environments) if environments is not None else set()).union([None])

        rollups = self.get_active_series(start, end, timestamp)

        for rollup, series in rollups.items():
            for model in models:
                for key in keys:
                    for environment in environments:
                        data = self.data[model][(key, environment)]
                        for timestamp in series:
                            data.pop(
                                self.normalize_to_rollup(timestamp, rollup),
                                set(),
                            )

    def flush(self):
        # self.data[model][key][rollup] = count
        self.data = defaultdict(
            lambda: defaultdict(
                lambda: defaultdict(
                    int,
                )
            )
        )

        # self.sets[model][key][rollup] = set of elements
        self.sets = defaultdict(
            lambda: defaultdict(
                lambda: defaultdict(
                    set,
                ),
            ),
        )

        # self.frequencies[model][key][rollup] = Counter()
        self.frequencies = defaultdict(
            lambda: defaultdict(
                lambda: defaultdict(
                    Counter,
                )
            ),
        )

    def record_frequency_multi(self, requests, timestamp=None, environment=None):
        environments = set([environment, None])

        if timestamp is None:
            timestamp = timezone.now()

        for model, request in requests:
            for key, items in request.items():
                items = {k: float(v) for k, v in items.items()}
                for environment in environments:
                    source = self.frequencies[model][(key, environment)]
                    for rollup in self.rollups:
                        source[self.normalize_to_rollup(timestamp, rollup)].update(items)

    def get_most_frequent(self, model, keys, start, end=None,
                          rollup=None, limit=None, environment=None):
        rollup, series = self.get_optimal_rollup_series(start, end, rollup)

        results = {}
        for key in keys:
            result = results[key] = Counter()
            source = self.frequencies[model][(key, environment)]
            for timestamp in series:
                result.update(source[self.normalize_ts_to_rollup(timestamp, rollup)])

        for key, counter in results.items():
            results[key] = counter.most_common(limit)

        return results

    def get_most_frequent_series(self, model, keys, start, end=None,
                                 rollup=None, limit=None, environment=None):
        rollup, series = self.get_optimal_rollup_series(start, end, rollup)

        results = {}
        for key in keys:
            result = results[key] = []
            source = self.frequencies[model][(key, environment)]
            for timestamp in series:
                data = source[self.normalize_ts_to_rollup(timestamp, rollup)]
                result.append((timestamp, dict(data.most_common(limit))))

        return results

    def get_frequency_series(self, model, items, start, end=None, rollup=None, environment=None):
        rollup, series = self.get_optimal_rollup_series(start, end, rollup)

        results = {}
        for key, members in items.items():
            result = results[key] = []
            source = self.frequencies[model][(key, environment)]
            for timestamp in series:
                scores = source[self.normalize_ts_to_rollup(timestamp, rollup)]
                result.append((timestamp, {k: scores.get(k, 0.0) for k in members}, ))

        return results

    def get_frequency_totals(self, model, items, start, end=None, rollup=None, environment=None):
        results = {}

        for key, series in six.iteritems(
            self.get_frequency_series(model, items, start, end, rollup, environment)
        ):
            result = results[key] = {}
            for timestamp, scores in series:
                for member, score in scores.items():
                    result[member] = result.get(member, 0.0) + score

        return results

    def merge_frequencies(self, model, destination, sources, timestamp=None, environments=None):
        environments = (set(environments) if environments is not None else set()).union([None])
        raise NotImplementedError

        destination = self.frequencies[model][destination]
        for source in sources:
            for bucket, counter in self.data[model].pop(source, {}).items():
                destination[bucket].update(counter)

    def delete_frequencies(self, models, keys, start=None, end=None,
                           timestamp=None, environments=None):
        environments = (set(environments) if environments is not None else set()).union([None])

        rollups = self.get_active_series(start, end, timestamp)

        for rollup, series in rollups.items():
            for model in models:
                for key in keys:
                    for environment in environments:
                        data = self.frequencies[model][(key, environment)]
                        for timestamp in series:
                            data.pop(
                                self.normalize_to_rollup(timestamp, rollup),
                                Counter(),
                            )
