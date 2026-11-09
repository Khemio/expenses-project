import os
from pprint import pprint

from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

def main():
    client = MongoClient(os.getenv("MONGO_URI"))

    try:
        db = client["expense_approval"]
        collection = db["receipts"]

        print("=== COLLECTION VALIDATION ===")

        info = db.command(
            "listCollections",
            filter={"name": "receipts"},
        )

        for item in info["cursor"]["firstBatch"]:
            options = item.get("options", {})
            pprint(options.get("validator", {}))
            print(
                "Validation action:",
                options.get("validationAction", "error"),
            )

        print("\n=== CURRENT RECEIPT COUNT ===")
        print(collection.count_documents({}))

        print("\n=== SAMPLE RECEIPTS ===")

        for receipt in collection.find().limit(3):
            pprint(receipt)

    finally:
        client.close()


if __name__ == "__main__":
    main()