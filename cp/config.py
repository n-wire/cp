import motor.motor_asyncio
import os
nw_server = os.environ['MONGO_DB'] if 'MONGO_DB' in os.environ else 'localhost'
mongo_client = motor.motor_asyncio.AsyncIOMotorClient(nw_server, 27017)