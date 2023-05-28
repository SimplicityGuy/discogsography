from datetime import datetime
from gzip import GzipFile
from os import getenv
from pathlib import Path

from discogs import download_discogs_data
from orjson import OPT_INDENT_2, OPT_SORT_KEYS, dumps
from pika import BlockingConnection, DeliveryMode, URLParameters
from pika.spec import BasicProperties
from xmltodict import parse

AMQP_CONNECTION = getenv("AMQP_CONNECTION")  # format: amqp://user:password@server:port
AMQP_EXCHANGE = "discogsography-extractor"
DISCOGS_ROOT = "/discogs-data"

MAX_TEMP_SIZE = 1e9  # 1000 Mb


class Extractor:
    def __init__(self, input_file: str):
        # `input_file` is in the format of: discogs_YYYYMMDD_datatype.xml.gz
        self.data_type = input_file.split("_")[2].split(".")[0]
        self.input_file = input_file
        self.input_path = Path(DISCOGS_ROOT, self.input_file)
        self.total_count: int = 0
        self.start_time = datetime.now()
        self.end_time = datetime.now()
        self.amqp_connection = None
        self.amqp_channel = None
        self.amqp_properties = BasicProperties(
            content_encoding="application/json", delivery_mode=DeliveryMode.Persistent
        )

    def _get_elapsed_time(self):
        return self.end_time - self.start_time

    elapsed_time = property(fget=_get_elapsed_time)

    def _get_tps(self):
        self.end_time = datetime.now()
        return self.total_count / self.elapsed_time.total_seconds()

    tps = property(fget=_get_tps)

    def __enter__(self):
        self.amqp_connection = BlockingConnection(URLParameters(AMQP_CONNECTION))
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

    def __exit__(self, exc_type, exc_value, exc_tb):
        self.amqp_connection.close()

    def extract(self):
        print(f" -=: Extracting {self.data_type} from the most recent Discogs data :=- ")
        self.start_time = datetime.now()
        parse(GzipFile(self.input_path.resolve()), item_depth=2, item_callback=self.__loader)
        self.end_time = datetime.now()

    def __loader(self, path, data):
        # `path` is in the format of:
        #   [('masters', None), ('master', OrderedDict([('id', '2'), ('status', 'Accepted')]))]
        #   [('releases', None), ('release', OrderedDict([('id', '2'), ('status', 'Accepted')]))]
        data_type = path[0][0]
        if data_type != self.data_type:
            print(
                f"data type ({data_type}) is not the same as the data type specified for this instance ({self.data_type})"
            )
            return False

        self.total_count += 1

        if data_type in ["masters", "releases"]:
            data["id"] = path[1][1]["id"]

        print(f" --: processing {self.data_type} [{data['id']:10}] :-- ")

        self.amqp_channel.basic_publish(
            body=dumps(data, option=OPT_SORT_KEYS | OPT_INDENT_2),
            exchange=AMQP_EXCHANGE,
            properties=self.amqp_properties,
            routing_key=self.data_type,
        )

        return True


def main():
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
    discogs_data = download_discogs_data(DISCOGS_ROOT)

    for discogs_data_file in discogs_data:
        if "CHECKSUM" in discogs_data_file:
            continue

        with Extractor(discogs_data_file) as extractor:
            extractor.extract()


if __name__ == "__main__":
    main()
