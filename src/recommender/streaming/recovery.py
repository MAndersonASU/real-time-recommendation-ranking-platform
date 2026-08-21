from confluent_kafka import TopicPartition

from recommender.streaming.kafka_client import DEFAULT_BOOTSTRAP_SERVERS, build_consumer


def report_consumer_lag(
    group_id: str,
    topic: str,
    num_partitions: int = 1,
    bootstrap_servers: str = DEFAULT_BOOTSTRAP_SERVERS,
) -> dict:
    """Per-partition lag for `group_id` on `topic`: how many messages
    exist on the broker beyond what this group has actually committed. A
    real operational signal -- a consumer group falling behind shows
    growing lag here before anything else would notice. Uses a throwaway
    Consumer bound to the target group id purely to query watermark and
    committed offsets; it never subscribes or polls, so checking lag
    never disturbs the group's real consumption position.
    """
    consumer = build_consumer(group_id, bootstrap_servers)
    try:
        result = {}
        for partition_id in range(num_partitions):
            tp = TopicPartition(topic, partition_id)
            _low, high = consumer.get_watermark_offsets(tp, timeout=10, cached=False)
            committed = consumer.committed([tp], timeout=10)[0]
            committed_offset = committed.offset if committed.offset is not None and committed.offset >= 0 else 0
            result[partition_id] = {
                "latest_offset": high,
                "committed_offset": committed_offset,
                "lag": max(high - committed_offset, 0),
            }
        return result
    finally:
        consumer.close()
