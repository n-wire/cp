import motor.motor_asyncio
nw_server = 'localhost'
mongo_client = motor.motor_asyncio.AsyncIOMotorClient(nw_server, 27017)