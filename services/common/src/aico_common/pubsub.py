"""Pub/Sub publisher (shared by the enumerator and the serving-shim).

The client batches asynchronously and ``publish()`` returns a future. The message is sent
when the future resolves. A short-lived process must call ``flush()`` before exiting.
The client is lazily imported and injectable for offline testing.
"""

from __future__ import annotations

import json


class PubSubPublisher:
    """Publishes ``{"url": ...}`` messages to a Pub/Sub topic (lazy client)."""

    def __init__(self, project: str, topic: str, *, client=None):
        self.project = project
        self.topic = topic
        self._client = client
        self._topic_path = None
        self._futures: list = []

    def _get(self):
        if self._client is None:
            from google.cloud import pubsub_v1

            self._client = pubsub_v1.PublisherClient()
        if self._topic_path is None:
            self._topic_path = self._client.topic_path(self.project, self.topic)
        return self._client, self._topic_path

    def publish(self, url: str) -> None:
        client, topic_path = self._get()
        # publish() batches and returns a future; the message is not actually sent
        # until the future resolves. A short-lived caller must flush() before exit or
        # the batch is silently dropped.
        self._futures.append(
            client.publish(topic_path, json.dumps({"url": url}).encode("utf-8"))
        )

    def flush(self) -> None:
        """Block until every published message is confirmed (raises on failure)."""
        for future in self._futures:
            future.result()
        self._futures.clear()
