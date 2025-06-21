import logging
from datetime import datetime, timedelta
from gzip import GzipFile
from pathlib import Path
from typing import Any

from dict_hash import sha256
from discogs import download_discogs_data
from orjson import OPT_INDENT_2, OPT_SORT_KEYS, dumps, loads
from pika import BlockingConnection, DeliveryMode, URLParameters
from pika.adapters.blocking_connection import BlockingChannel
from pika.spec import BasicProperties
from xmltodict import parse

from config import ExtractorConfig, setup_logging

logger = logging.getLogger(__name__)

AMQP_EXCHANGE = "discogsography-extractor"


class Extractor:
    def __init__(self, input_file: str, config: ExtractorConfig):
        # `input_file` is in the format of: discogs_YYYYMMDD_datatype.xml.gz
        self.data_type = input_file.split("_")[2].split(".")[0]
        self.input_file = input_file
        self.input_path = Path(config.discogs_root, self.input_file)
        self.config = config
        self.total_count: int = 0
        self.start_time = datetime.now()
        self.end_time = datetime.now()
        self.amqp_connection: BlockingConnection | None = None
        self.amqp_channel: BlockingChannel | None = None
        self.amqp_properties = BasicProperties(
            content_encoding="application/json", delivery_mode=DeliveryMode.Persistent
        )

    def _get_elapsed_time(self) -> timedelta:
        return self.end_time - self.start_time

    elapsed_time = property(fget=_get_elapsed_time)

    def _get_tps(self) -> float:
        self.end_time = datetime.now()
        elapsed_seconds: float = self.elapsed_time.total_seconds()
        if elapsed_seconds == 0:
            return 0.0
        return float(self.total_count) / elapsed_seconds

    tps = property(fget=_get_tps)

    def __enter__(self) -> "Extractor":
        self.amqp_connection = BlockingConnection(URLParameters(self.config.amqp_connection))
        self.amqp_channel = self.amqp_connection.channel()

        # Create the exchange to send the messages to.
        self.amqp_channel.exchange_declare(
            auto_delete=True, durable=True, exchange=AMQP_EXCHANGE, exchange_type="fanout"
        )

        # The exchange defined in `AMQP_EXCHANGE` fans out in 2 * (# of data types). This allows messages with
        # `routing_keys` for each data type to be handled by different workers concurrently. Further, data is
        # ingested into both PostgreSQL and neo4j, which allows different workers to handle those queues
        # independently.
        graphinator_queue_name = f"discogsography-graphinator-{self.data_type}"
        tableinator_queue_name = f"discogsography-tableinator-{self.data_type}"

        self.amqp_channel.queue_declare(
            auto_delete=True, durable=True, queue=graphinator_queue_name
        )
        self.amqp_channel.queue_bind(
            exchange=AMQP_EXCHANGE, queue=graphinator_queue_name, routing_key=self.data_type
        )

        self.amqp_channel.queue_declare(
            auto_delete=True, durable=True, queue=tableinator_queue_name
        )
        self.amqp_channel.queue_bind(
            exchange=AMQP_EXCHANGE, queue=tableinator_queue_name, routing_key=self.data_type
        )

        return self

    def __exit__(self, exc_type: Any, exc_value: Any, exc_tb: Any) -> None:
        if self.amqp_connection is not None:
            self.amqp_connection.close()

    def extract(self) -> None:
        logger.info(f"Starting extraction of {self.data_type} from Discogs data")
        self.start_time = datetime.now()
        parse(GzipFile(self.input_path.resolve()), item_depth=2, item_callback=self.__loader)
        self.end_time = datetime.now()

    def __loader(self, path: list[tuple[str, dict[str, Any] | None]], data: dict[str, Any]) -> bool:
        # `path` is in the format of:
        #   [('masters', None), ('master', OrderedDict([('id', '2'), ('status', 'Accepted')]))]
        #   [('releases', None), ('release', OrderedDict([('id', '2'), ('status', 'Accepted')]))]

        data_type = path[0][0]
        if data_type != self.data_type:
            logger.warning(f"Data type mismatch: expected {self.data_type}, got {data_type}")
            return False

        self.total_count += 1

        if data_type in ["masters", "releases"] and len(path) > 1 and path[1][1] is not None:
            data["id"] = path[1][1]["id"]

        logger.debug(f"Processing {self.data_type} item {data['id']}")

        data = loads(dumps(data, option=OPT_SORT_KEYS | OPT_INDENT_2))
        data["sha256"] = sha256(data)  # sha256 is computed on the original data, without the hash

        if self.amqp_channel is not None:
            self.amqp_channel.basic_publish(
                body=dumps(data, option=OPT_SORT_KEYS | OPT_INDENT_2),
                exchange=AMQP_EXCHANGE,
                properties=self.amqp_properties,
                routing_key=self.data_type,
            )

        return True


def main() -> None:
    config = ExtractorConfig.from_env()
    setup_logging("extractor", log_file=Path("extractor.log"))

    print("    ·▄▄▄▄  ▪  .▄▄ ·  ▄▄·        ▄▄ • .▄▄ ·      ")
    print("    ██▪ ██ ██ ▐█ ▀. ▐█ ▌▪▪     ▐█ ▀ ▪▐█ ▀.      ")
    print("    ▐█· ▐█▌▐█·▄▀▀▀█▄██ ▄▄ ▄█▀▄ ▄█ ▀█▄▄▀▀▀█▄     ")
    print("    ██. ██ ▐█▌▐█▄▪▐█▐███▌▐█▌.▐▌▐█▄▪▐█▐█▄▪▐█     ")
    print("    ▀▀▀▀▀• ▀▀▀ ▀▀▀▀ ·▀▀▀  ▀█▄▀▪·▀▀▀▀  ▀▀▀▀      ")
    print("▄▄▄ .▐▄• ▄ ▄▄▄▄▄▄▄▄   ▄▄▄·  ▄▄· ▄▄▄▄▄      ▄▄▄  ")
    print("▀▄.▀· █▌█▌▪•██  ▀▄ █·▐█ ▀█ ▐█ ▌▪•██  ▪     ▀▄ █·")
    print("▐▀▀▪▄ ·██·  ▐█.▪▐▀▀▄ ▄█▀▀█ ██ ▄▄ ▐█.▪ ▄█▀▄ ▐▀▀▄ ")
    print("▐█▄▄▌▪▐█·█▌ ▐█▌·▐█•█▌▐█ ▪▐▌▐███▌ ▐█▌·▐█▌.▐▌▐█•█▌")
    print(" ▀▀▀ •▀▀ ▀▀ ▀▀▀ .▀  ▀ ▀  ▀ ·▀▀▀  ▀▀▀  ▀█▄▀▪.▀  ▀")
    print()

    logger.info("Starting Discogs data extractor")
    discogs_data = download_discogs_data(str(config.discogs_root))

    for discogs_data_file in discogs_data:
        if "CHECKSUM" in discogs_data_file:
            continue

        with Extractor(discogs_data_file, config) as extractor:
            extractor.extract()


if __name__ == "__main__":
    main()
