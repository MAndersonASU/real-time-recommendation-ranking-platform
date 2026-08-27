from confluent_kafka import Consumer, Producer
from confluent_kafka.admin import AdminClient, NewTopic

DEFAULT_BOOTSTRAP_SERVERS = "localhost:9092"


def build_producer(bootstrap_servers: str = DEFAULT_BOOTSTRAP_SERVERS) -> Producer:
    return Producer({"bootstrap.servers": bootstrap_servers})


def build_consumer(
    group_id: str,
    bootstrap_servers: str = DEFAULT_BOOTSTRAP_SERVERS,
    auto_offset_reset: str = "earliest",
) -> Consumer:
    return Consumer(
        {
            "bootstrap.servers": bootstrap_servers,
            "group.id": group_id,
            "auto.offset.reset": auto_offset_reset,
            # Manual commits, deliberately: recovery testing
            # (docs/operations/recovery-testing.md) needs direct control over
            # exactly when an offset is
            # considered processed, which auto-commit would hide.
            "enable.auto.commit": False,
        }
    )


def ensure_topic(
    topic: str, num_partitions: int = 1, bootstrap_servers: str = DEFAULT_BOOTSTRAP_SERVERS
) -> None:
    admin = AdminClient({"bootstrap.servers": bootstrap_servers})
    existing = admin.list_topics(timeout=10).topics
    if topic in existing:
        return
    futures = admin.create_topics(
        [NewTopic(topic, num_partitions=num_partitions, replication_factor=1)]
    )
    for future in futures.values():
        future.result()
