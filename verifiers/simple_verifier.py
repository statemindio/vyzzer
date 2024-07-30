import json
import logging
import time

from config import Config
from db import get_mongo_client

# TODO: get level from config
logger = logging.getLogger("verifier")
logging.basicConfig(format='%(name)s:%(levelname)s:%(asctime)s:%(message)s', level=logging.DEBUG)


class VerifierException(Exception):
    pass


def storage_verifier(storage0, storage1):
    if storage0 != storage1:
        raise VerifierException(f"Storage discrepancy: {storage0} | {storage1}")


def memory_verifier(memory0, memory1):
    # TODO: come up with memory verification process
    # It seems like we won't me right to just compare this two values
    pass


def gas_verifier(gas0, gas1):
    pass


def return_value_verifier(value0, value1):
    loaded_value0 = value0
    loaded_value1 = value1
    if loaded_value0 != loaded_value1:
        raise VerifierException(f"Return Value discrepancy: {loaded_value0} | {loaded_value1}")


def verify_two_results(_res0, _res1):
    verifiers = {
        "Storage": (storage_verifier, (_res0["state"], _res1["state"])),
        "Memory": (memory_verifier, (_res0["memory"], _res1["memory"])),
        "Gas": (gas_verifier, (_res0["consumed_gas"], _res1["consumed_gas"])),
        "Return_Value": (return_value_verifier, (_res0["return_value"], _res1["return_value"]))
    }
    d = {}
    for name, (verifier, params) in verifiers.items():
        try:
            verifier(*params)
            d[name] = None
        except VerifierException as e:
            d[name] = str(e)
            continue
    return d


def verify_results(_results):
    compilers = list(_results["results"].keys())

    func_results = []
    for _res in zip(*[_results["results"][compiler_key] for compiler_key in compilers]):
        logger.debug(f"Function result: {_res}")

        # each item of `r` is a list of comparisons of a function
        r = []

        for i, _func_res in enumerate(_res):
            if i == len(_res) - 1:
                break
            d = verify_two_results(_func_res, _res[i + 1])
            r.append({
                "compilers": (compilers[i], compilers[i + 1]),
                "results": d
            })
        func_results.append(r)
    return func_results


if __name__ == '__main__':
    conf = Config()
    db_client = get_mongo_client(conf.db["host"], conf.db["port"])
    results_collection = db_client["run_results"]
    verification_results_collection = db_client["verification_results"]

    while True:
        unhandled_results = list(results_collection.find({"is_handled": False}))
        logger.debug(f"Unhandled results received: {unhandled_results}")

        verification_results = []
        for res in unhandled_results:
            logger.info(f"Handling result: {res['generation_id']}")
            logger.debug(res)
            _r = verify_results(res)
            verification_results.append({"generation_id": res["generation_id"], "results": _r})

        if len(verification_results) != 0:
            verification_results_collection.insert_many(verification_results)

        if len(unhandled_results) != 0:
            results_collection.update_many(
                {"_id": {"$in": [r["_id"] for r in unhandled_results]}},
                {"$set": {"is_handled": True}}
            )
        time.sleep(5)