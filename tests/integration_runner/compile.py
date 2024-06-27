import json
import os

import pika.exceptions
# from vyper import compile_code
import vyper

from db import get_mongo_client
from bson.objectid import ObjectId

db_ = get_mongo_client()
compilation_results = db_["compilation_results"]
queue_collection = db_["compilation_log"]

connection = pika.BlockingConnection(pika.ConnectionParameters(
    host=os.environ.get('QUEUE_BROKER_HOST', 'localhost'),
    port=int(os.environ.get('QUEUE_BROKER_PORT', 5672))
))
channel = connection.channel()

queue_name = 'queue3.10'

channel.queue_declare(queue_name)


def callback(ch, method, properties, body):
    data = json.loads(body)
    print(data["_id"])
    gen = {
        "generation_id": data["_id"]
    }
    try:
        comp = vyper.compile_code(data["generation_result"])
        gen.update(comp)
        queue_collection.update_one({"_id": ObjectId(data["_id"])},
                                    {"$set": {f"compiled_{vyper.__version__.replace('.', '_')}": True}})
    except Exception as e:
        gen.update({"error": str(e)})
    compilation_results.insert_one(gen)


while True:
    try:
        channel.basic_consume(queue_name, on_message_callback=callback, auto_ack=True)
        channel.start_consuming()
    except (pika.exceptions.StreamLostError, pika.exceptions.ChannelWrongStateError):
        pass
