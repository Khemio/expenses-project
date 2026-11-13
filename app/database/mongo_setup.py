
import os

from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.errors import OperationFailure

load_dotenv()


def setup_receipts_collection():
    mongo_uri = os.getenv("MONGO_URI")

    if not mongo_uri:
        raise ValueError("MONGO_URI is missing from .env")

    client = MongoClient(
        mongo_uri,
        serverSelectionTimeoutMS=5000,
    )

    try:
        db = client["expense_approval"]
        collection_name = "receipts"

        receipt_schema = {
            "$jsonSchema": {
                "bsonType": "object",
                "required": [
                    "expense_id",
                    "vendor",
                    "country",
                    "vat_number",
                    "total",
                    "currency",
                    "receipt_date",
                ],
                "properties": {
                    "expense_id": {
                        "bsonType": "int",
                    },
                    "vendor": {
                        "bsonType": "string",
                    },
                    "country": {
                        "bsonType": "string",
                    },
                    "vat_number": {
                        "bsonType": "string",
                    },
                    "total": {
                        "bsonType": ["double", "decimal"],
                        "minimum": 0,
                    },
                    "currency": {
                        "bsonType": "string",
                    },
                    "receipt_date": {
                        "bsonType": "date",
                    },
                    "details": {
                        "bsonType": "object",
                    },
                },
            }
        }

        # if collection_name in db.list_collection_names():
        #     db.drop_collection(collection_name)

        # db.create_collection(
        #     collection_name,
        #     validator=receipt_schema,
        #     validationLevel="strict",
        #     validationAction="error",
        # )

        if collection_name not in db.list_collection_names():
            db.create_collection(
                collection_name,
                validator=receipt_schema,
                validationLevel="strict",
                validationAction="error",
            )
        else:
            db.command(
                "collMod",
                collection_name,
                validator=receipt_schema,
                validationLevel="strict",
                validationAction="error",
            )

        print("MongoDB receipts collection created with JSON Schema validation.")

    finally:
        client.close()


if __name__ == "__main__":
    setup_receipts_collection()
